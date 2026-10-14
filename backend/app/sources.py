import re

from psycopg.types.json import Jsonb

from app.auth import AccessError, lock_service, principal


async def available(connection, owner_id, scope):
    return await (await connection.execute(
        """SELECT s.*,f.name FROM available_source_revisions s LEFT JOIN document_files f ON f.document_id=s.document_id
           WHERE s.owner_id=%s AND s.document_id=ANY(%s::uuid[]) ORDER BY s.document_id""",
        (owner_id, scope),
    )).fetchall()


async def retrieve(connection, owner_id, scope, embedding, *, limit=12, min_similarity=0.75):
    vector = '[' + ','.join(map(str, embedding)) + ']'
    return await (await connection.execute(
        """SELECT c.*,s.document_id,s.mode,s.limitations,f.name,1-(c.embedding <=> %s::vector) AS similarity
        FROM source_chunks c JOIN available_source_revisions s ON s.revision_id=c.revision_id
        LEFT JOIN document_files f ON f.document_id=s.document_id
        WHERE s.owner_id=%s AND s.document_id=ANY(%s::uuid[]) AND c.kind<>'skip'
          AND (s.mode<>'skip_handwriting' OR c.kind='printed')
          AND 1-(c.embedding <=> %s::vector)>=%s
        ORDER BY c.embedding <=> %s::vector,c.id LIMIT %s""",
        (vector, owner_id, scope, vector, min_similarity, vector, limit),
    )).fetchall()


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


async def history(connection, request):
    # UI snapshots retain every message; only whole eligible pairs enter model context.
    return await (await connection.execute(
        """SELECT r.id AS request_id,u.text AS question,a.text AS answer,
          coalesce((SELECT jsonb_agg(jsonb_build_object('document_id',s.document_id,'revision_id',s.revision_id))
                    FROM request_sources s WHERE s.request_id=r.id),'[]') AS dependencies
        FROM requests r JOIN messages u ON u.request_id=r.id AND u.role='user'
          JOIN messages a ON a.request_id=r.id AND a.role='assistant'
        WHERE r.conversation_id=%s AND r.owner_id=%s AND r.state='completed' AND NOT a.excluded
          AND NOT EXISTS (SELECT 1 FROM request_sources p LEFT JOIN available_source_revisions s
            ON s.document_id=p.document_id AND s.revision_id=p.revision_id AND s.owner_id=r.owner_id
            WHERE p.request_id=r.id AND (s.revision_id IS NULL OR NOT (p.document_id=ANY(%s::uuid[]))))
        ORDER BY r.created_at,r.id""",
        (request['conversation_id'], request['owner_id'], request['scope']),
    )).fetchall()


async def source_flags(connection, request_id):
    rows = await (await connection.execute(
        """SELECT s.document_id,s.revision_id,d.deleted,d.published_revision<>s.revision_id AS corrected
        FROM request_sources s JOIN documents d ON d.id=s.document_id WHERE s.request_id=%s""", (request_id,),
    )).fetchall()
    return {str(row['document_id']): 'deleted' if row['deleted'] else 'corrected'
            for row in rows if row['deleted'] or row['corrected']}


async def change_source(connection, token, document_id, *, deleted=False, revision_id=None):
    """Publisher boundary: switch a complete staged revision, or soft-delete its document."""
    async with connection.transaction():
        await lock_service(connection)
        actor = await principal(connection, token)
        return await switch_source(connection, actor, document_id, deleted=deleted, revision_id=revision_id)


async def switch_source(connection, actor, document_id, *, deleted=False, revision_id=None):
    """Internal publisher shares the authorized transaction and owner/source locks."""
    from app.answers import transition

    document = await (await connection.execute(
        "SELECT * FROM documents WHERE id=%s AND owner_id=%s FOR UPDATE", (document_id, actor['id']),
    )).fetchone()
    if not document:
        raise AccessError('not_found', 404)
    if deleted and document['deleted']:
        return
    if not deleted and document['deleted']:
        raise AccessError('source_deleted', 409)
    if not deleted and revision_id == document['published_revision']:
        return
    if not deleted:
        await connection.execute("SELECT id FROM source_revisions WHERE id=%s AND document_id=%s FOR UPDATE", (revision_id, document_id))
        revision = await (await connection.execute(
            """SELECT r.* FROM source_revisions r WHERE id=%s AND document_id=%s
            AND status='published' AND upload_complete
            AND (mode='complete' OR (skip_confirmed AND jsonb_array_length(limitations)>0))
            AND (SELECT count(*) FROM source_pages p WHERE p.revision_id=r.id)=r.page_count
            AND NOT EXISTS(SELECT 1 FROM source_pages p WHERE p.revision_id=r.id AND (status<>'ready' OR page>r.page_count))""",
            (revision_id, document_id),
        )).fetchone()
        if not revision:
            raise AccessError('revision_not_ready', 409)
    affected = await (await connection.execute(
        """SELECT DISTINCT r.conversation_id FROM requests r JOIN request_sources s ON s.request_id=r.id
           WHERE s.document_id=%s ORDER BY r.conversation_id""", (document_id,),
    )).fetchall()
    for row in affected:
        await connection.execute("SELECT id FROM conversations WHERE id=%s FOR UPDATE", (row['conversation_id'],))
    await connection.execute("UPDATE documents SET deleted=%s,published_revision=coalesce(%s,published_revision) WHERE id=%s", (deleted, revision_id, document_id))
    # Provenance already includes all ancestors actually passed to this answer.
    for row in affected:
        await connection.execute("UPDATE conversations SET context_epoch=context_epoch+1 WHERE id=%s", (row['conversation_id'],))
    requests = await (await connection.execute(
        """SELECT r.* FROM requests r WHERE EXISTS(SELECT 1 FROM request_sources s WHERE s.request_id=r.id AND s.document_id=%s)
           ORDER BY r.id FOR UPDATE""", (document_id,),
    )).fetchall()
    for request in requests:
        flags = await source_flags(connection, request['id'])
        await connection.execute("UPDATE messages SET excluded=true,source_flags=%s WHERE request_id=%s AND role='assistant'", (Jsonb(flags), request['id']))
        if deleted:
            await transition(connection, request, 'interrupted', 'source_deleted')
