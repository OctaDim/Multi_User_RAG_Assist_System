import re

from sqlalchemy import Text, and_, cast, column, func, or_, select, table, union, update
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.auth import AccessError, lock_service, principal
from app.configuration import load_settings
from app.models import Conversation, Document, DocumentFile, Message, Request, RequestSource, SourceChunk, SourcePage, SourceRevision


available_revisions = table(
    'available_source_revisions',
    column('document_id', UUID), column('owner_id', UUID), column('revision_id', UUID),
    column('mode', Text), column('limitations', JSONB),
)


def scoped_document_ids(request_id):
    return union(
        select(func.unnest(Request.scope).label('document_id')).where(Request.id == request_id),
        select(RequestSource.document_id).where(RequestSource.request_id == request_id),
    )


async def available(session, owner_id, scope):
    rows = await session.execute(
        select(available_revisions, DocumentFile.name)
        .outerjoin(DocumentFile, DocumentFile.document_id == available_revisions.c.document_id)
        .where(available_revisions.c.owner_id == owner_id, available_revisions.c.document_id.in_(scope))
        .order_by(available_revisions.c.document_id)
    )
    return [dict(row) for row in rows.mappings()]


async def retrieve(session, owner_id, scope, embedding, *, limit=None, min_similarity=None):
    config = load_settings('runtime')['rag']
    limit = config['retrieval_limit'] if limit is None else limit
    min_similarity = config['min_similarity'] if min_similarity is None else min_similarity
    distance = SourceChunk.embedding.cosine_distance(embedding)
    rows = await session.execute(
        select(SourceChunk.__table__, available_revisions.c.document_id, available_revisions.c.mode,
               available_revisions.c.limitations, DocumentFile.name, (1-distance).label('similarity'))
        .join(available_revisions, available_revisions.c.revision_id == SourceChunk.revision_id)
        .outerjoin(DocumentFile, DocumentFile.document_id == available_revisions.c.document_id)
        .where(available_revisions.c.owner_id == owner_id, available_revisions.c.document_id.in_(scope),
               SourceChunk.kind != 'skip',
               or_(available_revisions.c.mode != 'skip_handwriting', SourceChunk.kind == 'printed'),
               1-distance >= min_similarity)
        .order_by(distance, SourceChunk.id).limit(limit)
    )
    return [dict(row) for row in rows.mappings()]


def validate_citations(citations, passport):
    allowed = {value['id']: value for value in passport['passed']}
    for citation in citations:
        if not isinstance(citation, dict):
            raise AccessError('invalid_citation', 422)
        span = allowed.get(citation.get('id'))
        if span is None:
            raise AccessError('invalid_citation', 422)
        start, end = citation.get('start'), citation.get('end')
        if (not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool)
            or not span['span_start'] <= start < end <= span['span_end']
            or citation.get('quote') != span['text'][start-span['span_start']:end-span['span_start']]):
            raise AccessError('invalid_citation', 422)
    return citations


def cited_spans(text, passport):
    fragments = passport.get('passed', [])
    citations, seen = [], set()
    for match in re.finditer(r'\[source:([1-9][0-9]?)\]', text):
        number = int(match.group(1))
        if number > len(fragments) or number in seen:
            continue
        fragment = fragments[number-1]
        citation = {'number':number, 'id':fragment['id'], 'document_id':fragment['document_id'],
                    'revision_id':fragment['revision_id'], 'page':fragment['page'], 'name':fragment.get('name'),
                    'start':fragment['span_start'], 'end':fragment['span_end'], 'quote':fragment['text']}
        validate_citations([citation], passport)
        citations.append(citation)
        seen.add(number)
    return citations


async def history(session, request):
    # UI snapshots retain every message; only whole eligible pairs enter model context.
    question, answer = Message.__table__.alias('question'), Message.__table__.alias('answer')
    dependencies = (
        select(func.jsonb_agg(func.jsonb_build_object(
            'document_id', RequestSource.document_id, 'revision_id', RequestSource.revision_id)))
        .where(RequestSource.request_id == Request.id).correlate(Request).scalar_subquery()
    )
    unavailable = (
        select(1).select_from(RequestSource)
        .outerjoin(available_revisions, and_(
            available_revisions.c.document_id == RequestSource.document_id,
            available_revisions.c.revision_id == RequestSource.revision_id,
            available_revisions.c.owner_id == Request.owner_id))
        .where(RequestSource.request_id == Request.id,
               or_(available_revisions.c.revision_id.is_(None), RequestSource.document_id.not_in(request['scope'])))
        .correlate(Request).exists()
    )
    rows = await session.execute(
        select(Request.id.label('request_id'), question.c.text.label('question'), answer.c.text.label('answer'),
               func.coalesce(dependencies, cast([], JSONB)).label('dependencies'))
        .join(question, and_(question.c.request_id == Request.id, question.c.role == 'user'))
        .join(answer, and_(answer.c.request_id == Request.id, answer.c.role == 'assistant'))
        .where(Request.conversation_id == request['conversation_id'], Request.owner_id == request['owner_id'],
               Request.state == 'completed', ~answer.c.excluded, ~unavailable)
        .order_by(Request.created_at, Request.id)
    )
    return [dict(row) for row in rows.mappings()]


async def source_flags(session, request_id):
    return (await source_flags_for(session, [request_id])).get(request_id, {})


async def source_flags_for(session, request_ids):
    rows = await session.execute(
        select(RequestSource.request_id, RequestSource.document_id, Document.deleted,
               (Document.published_revision != RequestSource.revision_id).label('corrected'))
        .join(Document, Document.id == RequestSource.document_id).where(RequestSource.request_id.in_(request_ids))
    )
    flags = {}
    for row in rows.mappings():
        if row['deleted'] or row['corrected']:
            flags.setdefault(row['request_id'], {})[str(row['document_id'])] = 'deleted' if row['deleted'] else 'corrected'
    return flags


async def change_source(session, token, document_id, *, deleted=False, revision_id=None):
    """Publisher boundary: switch a complete staged revision, or soft-delete its document."""
    async with session.begin():
        await lock_service(session)
        actor = await principal(session, token)
        return await switch_source(session, actor, document_id, deleted=deleted, revision_id=revision_id)


async def switch_source(session, actor, document_id, *, deleted=False, revision_id=None):
    """Internal publisher shares the authorized transaction and owner/source locks."""
    from app.answers import transition, event

    document = (await session.execute(
        select(Document.__table__).where(Document.id == document_id, Document.owner_id == actor['id']).with_for_update()
    )).mappings().first()
    if not document:
        raise AccessError('not_found', 404)
    if deleted and document['deleted']:
        return
    if not deleted and document['deleted']:
        raise AccessError('source_deleted', 409)
    if not deleted and revision_id == document['published_revision']:
        return
    if not deleted:
        await session.execute(select(SourceRevision.id).where(
            SourceRevision.id == revision_id, SourceRevision.document_id == document_id).with_for_update())
        page_count = (select(func.count()).select_from(SourcePage)
                      .where(SourcePage.revision_id == SourceRevision.id).correlate(SourceRevision).scalar_subquery())
        invalid_page = (select(1).where(SourcePage.revision_id == SourceRevision.id,
                        or_(SourcePage.status != 'ready', SourcePage.page > SourceRevision.page_count))
                        .correlate(SourceRevision).exists())
        revision = (await session.execute(
            select(SourceRevision.id).where(
                SourceRevision.id == revision_id, SourceRevision.document_id == document_id,
                SourceRevision.status == 'published', SourceRevision.upload_complete,
                or_(SourceRevision.mode == 'complete', and_(SourceRevision.skip_confirmed,
                    func.jsonb_array_length(SourceRevision.limitations) > 0)),
                page_count == SourceRevision.page_count, ~invalid_page)
        )).first()
        if not revision:
            raise AccessError('revision_not_ready', 409)
    affected = (await session.execute(
        select(Request.conversation_id).join(RequestSource, RequestSource.request_id == Request.id)
        .where(RequestSource.document_id == document_id).distinct().order_by(Request.conversation_id)
    )).scalars().all()
    for conversation_id in affected:
        await session.execute(select(Conversation.id).where(Conversation.id == conversation_id).with_for_update())
    await session.execute(update(Document.__table__).where(Document.id == document_id).values(
        deleted=deleted, published_revision=func.coalesce(revision_id, Document.published_revision)))
    # Provenance already includes all ancestors actually passed to this answer.
    for conversation_id in affected:
        await session.execute(update(Conversation.__table__).where(Conversation.id == conversation_id)
                              .values(context_epoch=Conversation.context_epoch+1))
    rows = await session.execute(
        select(Request.__table__).where(select(1).where(
            RequestSource.request_id == Request.id, RequestSource.document_id == document_id).exists())
        .order_by(Request.id).with_for_update()
    )
    for row in rows.mappings():
        request = dict(row)
        flags = await source_flags(session, request['id'])
        await session.execute(update(Message.__table__).where(Message.request_id == request['id'], Message.role == 'assistant')
                              .values(excluded=True, source_flags=flags))
        if deleted:
            request = await transition(session, request, 'interrupted', 'source_deleted')
        updated = dict((await session.execute(update(Request.__table__).where(Request.id == request['id'])
                       .values(version=Request.version+1).returning(*Request.__table__.c))).mappings().one())
        await event(session, updated, 'source_status', {'version': updated['version'], 'source_flags': flags,
            'excluded': bool(flags) or updated['state'] in ('interrupted', 'failed'),
            'state': updated['state'], 'reason': updated['reason']})
