import hashlib
import os
from pathlib import Path
import tomllib
from uuid import uuid4

from sqlalchemy import case, func, insert, null, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.auth import AccessError, lock_service, principal
from app.resources import resource_path
from app.models import Account, Document, DocumentFile, DocumentPageText, DocumentPolicy, DocumentPolicyAudit


LIMIT_KEYS = ('file_bytes', 'pdf_pages', 'batch_files', 'documents', 'original_bytes')
PERMISSION_KEYS = ('pdf', 'docx', 'txt', 'md', 'handwriting')


def public_documents():
    return select(
        Document.id, Document.owner_id, Document.ready, Document.deleted, DocumentFile.name,
        DocumentFile.format, DocumentFile.state, DocumentFile.error, DocumentFile.failure_page,
        DocumentFile.declared_bytes, DocumentFile.original_sha256, DocumentFile.mode, Document.published_revision,
    ).join(DocumentFile, DocumentFile.document_id == Document.id)


def page_texts(revision_id):
    return select(DocumentPageText.page, DocumentPageText.text, DocumentPageText.regions).where(
        DocumentPageText.revision_id == revision_id).order_by(DocumentPageText.page)


def defaults():
    with (resource_path('config')/'documents.toml').open('rb') as source:
        result = tomllib.load(source)
    validate_policy(result)
    return result


def validate_policy(value):
    if (set(value) != {'limits', 'permissions'} or set(value['limits']) != set(LIMIT_KEYS)
        or set(value['permissions']) != set(PERMISSION_KEYS)
        or any(type(v) is not int or v < 1 for v in value['limits'].values())
        or any(type(v) is not bool for v in value['permissions'].values())):
        raise AccessError('invalid_document_policy', 422)


async def initialize_policy(session, owner_id):
    config = defaults()
    await session.execute(pg_insert(DocumentPolicy).values(
        owner_id=owner_id, limits=config['limits'], permissions=config['permissions']).on_conflict_do_nothing())


async def policy(session, owner_id, *, exclusive=False):
    if not (await session.execute(select(Account.id).where(Account.id == owner_id))).first():
        raise AccessError('not_found', 404)
    await initialize_policy(session, owner_id)
    return dict((await session.execute(select(DocumentPolicy.__table__).where(DocumentPolicy.owner_id == owner_id)
                .with_for_update(read=not exclusive))).mappings().one())


def storage():
    value = os.environ.get('RAG_ORIGINALS_DIR')
    if not value:
        raise AccessError('original_storage_not_configured', 503)
    root = Path(value).resolve()
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        raise AccessError('original_storage_unavailable', 503) from None
    return root


def original_path(document_id):
    # Client filenames are labels; UUIDs alone identify immutable stored files.
    return storage()/f'{document_id}.original'


async def owned(session, actor, document_id, *, write=False):
    row = (await session.execute(public_documents().where(Document.id == document_id)
           .with_for_update(read=not write, of=[Document, DocumentFile]))).mappings().first()
    if not row or row['deleted'] or (row['owner_id'] != actor['id'] and (write or actor['role'] != 'super_admin')):
        raise AccessError('not_found', 404)
    return dict(row)


async def admit_uploads(session, token, files):
    if not files:
        raise AccessError('empty_upload', 422)
    storage()
    async with session.begin():
        await lock_service(session)
        actor = await principal(session, token)
        config = await policy(session, actor['id'], exclusive=True)
        limits, permissions = config['limits'], config['permissions']
        if len(files) > limits['batch_files']:
            raise AccessError('batch_limit', 413)
        normalized = []
        for file in files:
            name, size = file['name'], file['size']
            extension = Path(name).suffix.lower().lstrip('.')
            if not name or len(name) > 255 or '\x00' in name or extension not in PERMISSION_KEYS[:4]:
                raise AccessError('unsupported_document_format', 422)
            if type(size) is not int or size < 1:
                raise AccessError('invalid_upload_size', 422)
            if not permissions[extension]:
                raise AccessError('document_format_forbidden')
            if size > limits['file_bytes']:
                raise AccessError('file_size_limit', 413)
            normalized.append((name, extension, size))
        usage = (await session.execute(
            select(func.count().label('documents'), func.coalesce(func.sum(DocumentFile.declared_bytes), 0).label('bytes'))
            .select_from(DocumentFile).join(Document, Document.id == DocumentFile.document_id)
            .where(Document.owner_id == actor['id'], ~Document.deleted,
                   or_(DocumentFile.state.in_(('receiving', 'queued', 'processing', 'awaiting_choice', 'ready')),
                       DocumentFile.original_sha256.is_not(None)))
        )).mappings().one()
        if usage['documents'] + len(files) > limits['documents'] or usage['bytes'] + sum(f[2] for f in normalized) > limits['original_bytes']:
            raise AccessError('document_storage_limit', 413)
        batch_id, result = uuid4(), []
        for name, extension, size in normalized:
            document_id = uuid4()
            await session.execute(insert(Document).values(id=document_id, owner_id=actor['id']))
            await session.execute(insert(DocumentFile).values(
                document_id=document_id, batch_id=batch_id, name=name, format=extension,
                declared_bytes=size, state='receiving', admitted_limits=limits,
                admitted_handwriting_epoch=config['handwriting_epoch']))
            result.append({'id': document_id, 'name': name, 'state': 'receiving', 'ready': False})
        return {'batch_id': batch_id, 'documents': result}


async def fail_upload(session, document_id, reason, original_digest=None):
    async with session.begin():
        await lock_service(session)
        await session.execute(update(DocumentFile.__table__).where(DocumentFile.document_id == document_id).values(
            state=case((DocumentFile.state == 'receiving', 'failed'), else_=DocumentFile.state),
            error=case((DocumentFile.state == 'receiving', reason), else_=DocumentFile.error),
            original_sha256=func.coalesce(DocumentFile.original_sha256, original_digest)))


async def upload(database, token, document_id, stream):
    temporary = storage()/f'{document_id}.upload'
    async with database.session() as session, session.begin():
        await lock_service(session)
        actor = await principal(session, token)
        row = await owned(session, actor, document_id, write=True)
        if row['state'] != 'receiving':
            raise AccessError('upload_already_received', 409)
    try:
        output = temporary.open('xb')
    except FileExistsError:
        raise AccessError('upload_in_progress', 409) from None
    total, digest, linked = 0, hashlib.sha256(), False
    try:
        with output:
            async for chunk in stream:
                total += len(chunk)
                if total > row['declared_bytes']:
                    raise AccessError('upload_size_mismatch', 413)
                async with database.session() as session, session.begin():
                    await lock_service(session)
                    actor = await principal(session, token)
                    config = await policy(session, actor['id'])
                    current = await owned(session, actor, document_id, write=True)
                    if current['state'] != 'receiving' or not config['permissions'][row['format']]:
                        raise AccessError('upload_cancelled', 409)
                    output.write(chunk)
                    digest.update(chunk)
            output.flush()
            os.fsync(output.fileno())
        if total != row['declared_bytes']:
            raise AccessError('upload_size_mismatch', 422)
        async with database.session() as session, session.begin():
            await lock_service(session)
            actor = await principal(session, token)
            config = await policy(session, actor['id'])
            current = await owned(session, actor, document_id, write=True)
            if current['state'] != 'receiving' or not config['permissions'][row['format']]:
                raise AccessError('upload_cancelled', 409)
            state = 'awaiting_choice' if row['format'] == 'pdf' and not config['permissions']['handwriting'] else 'queued'
            # link is atomic and refuses to overwrite an existing immutable original.
            os.link(temporary, original_path(document_id))
            linked = True
            temporary.unlink()
            await session.execute(update(DocumentFile.__table__).where(DocumentFile.document_id == document_id)
                                  .values(state=state, original_sha256=digest.hexdigest()))
            return dict(current, state=state, original_sha256=digest.hexdigest())
    except BaseException as error:
        temporary.unlink(missing_ok=True)
        async with database.session() as session:
            # A missing COMMIT ACK must not delete a potentially committed original.
            await fail_upload(session, document_id, error.code if isinstance(error, AccessError) else 'upload_failed',
                              digest.hexdigest() if linked else None)
        raise


async def listing(session, token, owner_id=None):
    async with session.begin():
        await lock_service(session)
        actor = await principal(session, token)
        return await listing_view(session, actor, owner_id)


async def listing_view(session, actor, owner_id=None):
    owner_id = owner_id or actor['id']
    if owner_id != actor['id'] and actor['role'] != 'super_admin':
        raise AccessError('not_found', 404)
    rows = await session.execute(public_documents().where(Document.owner_id == owner_id, ~Document.deleted)
                                 .order_by(DocumentFile.created_at, Document.id))
    return {'documents': [dict(row) for row in rows.mappings()], 'readonly': owner_id != actor['id']}


async def read(session, token, document_id):
    async with session.begin():
        await lock_service(session)
        actor = await principal(session, token)
        return await read_view(session, actor, document_id)


async def read_view(session, actor, document_id):
    row = await owned(session, actor, document_id)
    if not row['ready']:
        raise AccessError('document_not_ready', 409)
    pages = (await session.execute(page_texts(row['published_revision']))).mappings()
    return {'document': row, 'pages': [dict(page) for page in pages]}


async def read_original(session, token, document_id):
    async with session.begin():
        await lock_service(session)
        actor = await principal(session, token)
        return await read_original_view(session, actor, document_id)


async def read_original_view(session, actor, document_id):
    row = await owned(session, actor, document_id)
    if not row['original_sha256']:
        raise AccessError('original_not_received', 409)
    return row


async def read_policy(session, token, owner_id):
    async with session.begin():
        await lock_service(session)
        actor = await principal(session, token)
        return await read_policy_view(session, actor, owner_id)


async def read_policy_view(session, actor, owner_id):
    if owner_id != actor['id'] and actor['role'] not in ('admin', 'super_admin'):
        raise AccessError('forbidden')
    return await policy(session, owner_id)


async def update_policy(session, token, owner_id, value):
    validate_policy(value)
    async with session.begin():
        await lock_service(session, exclusive=True)
        actor = await principal(session, token)
        if actor['role'] not in ('admin', 'super_admin'):
            raise AccessError('forbidden')
        previous = await policy(session, owner_id, exclusive=True)
        await session.execute(update(DocumentPolicy.__table__).where(DocumentPolicy.owner_id == owner_id)
                              .values(limits=value['limits'], permissions=value['permissions']))
        revoked = [key for key in PERMISSION_KEYS[:4] if previous['permissions'][key] and not value['permissions'][key]]
        if revoked:
            await session.execute(update(DocumentFile.__table__).where(
                Document.id == DocumentFile.document_id, Document.owner_id == owner_id,
                DocumentFile.format.in_(revoked), DocumentFile.correction_pages.is_(None),
                DocumentFile.state.in_(('receiving', 'queued', 'processing', 'awaiting_choice')))
                .values(state='failed', error='document_permission_revoked', job_id=None))
        if previous['permissions']['handwriting'] and not value['permissions']['handwriting']:
            await session.execute(update(DocumentPolicy.__table__).where(DocumentPolicy.owner_id == owner_id)
                                  .values(handwriting_epoch=DocumentPolicy.handwriting_epoch+1))
            await session.execute(update(DocumentFile.__table__).where(
                Document.id == DocumentFile.document_id, Document.owner_id == owner_id,
                DocumentFile.format == 'pdf', DocumentFile.mode == 'complete',
                DocumentFile.correction_pages.is_(None), DocumentFile.state.in_(('queued', 'processing')))
                .values(state='awaiting_choice', error='handwriting_permission_revoked', job_id=None))
        await session.execute(insert(DocumentPolicyAudit).values(actor_id=actor['id'], target_id=owner_id,
                              previous={'limits': previous['limits'], 'permissions': previous['permissions']}, updated=value))
        # Workers recheck permissions at every safe page/publication boundary.
        return value


async def choose_mode(session, token, document_id, choice):
    async with session.begin():
        await lock_service(session)
        actor = await principal(session, token)
        config = await policy(session, actor['id'])
        row = await owned(session, actor, document_id, write=True)
        if row['format'] != 'pdf' or row['state'] not in ('awaiting_choice', 'ready'):
            raise AccessError('document_choice_unavailable', 409)
        if choice == 'cancel':
            if row['ready']:
                raise AccessError('document_choice_unavailable', 409)
            await session.execute(update(DocumentFile.__table__).where(DocumentFile.document_id == document_id)
                                  .values(state='cancelled', job_id=None))
            return dict(row, state='cancelled')
        if choice not in ('complete', 'skip_handwriting'):
            raise AccessError('invalid_document_mode', 422)
        if not config['permissions']['pdf'] or (choice=='complete' and not config['permissions']['handwriting']):
            raise AccessError('document_permission_revoked')
        limits = config['limits'] if row['ready'] or row['error']=='handwriting_permission_revoked' else None
        if limits and row['declared_bytes'] > limits['file_bytes']:
            raise AccessError('file_size_limit', 413)
        values = dict(mode=choice, state='queued', job_id=None, error=None, failure_page=None,
                      admitted_handwriting_epoch=config['handwriting_epoch'], correction_pages=null(), correction_base=None)
        if limits:
            values['admitted_limits'] = limits
        await session.execute(update(DocumentFile.__table__).where(DocumentFile.document_id == document_id).values(**values))
        return dict(row, state='queued', mode=choice)


async def correct(session, token, document_id, base_revision, pages):
    async with session.begin():
        await lock_service(session)
        actor = await principal(session, token)
        row = await owned(session, actor, document_id, write=True)
        if not row['ready'] or row['published_revision'] != base_revision or row['state'] in ('queued','processing'):
            raise AccessError('document_revision_changed', 409)
        previous = (await session.execute(page_texts(base_revision))).mappings().all()
        if [page['page'] for page in pages] != [page['page'] for page in previous]:
            raise AccessError('incomplete_document_correction', 422)
        updated = []
        for before, after in zip(previous, pages):
            text = after['text']
            if '\x00' in text:
                raise AccessError('invalid_document_text', 422)
            regions = []
            cursor = 0
            for region in before['regions']:
                if region['kind'] != 'skip':
                    continue
                marker = before['text'][region['start']:region['end']]
                start = text.find(marker, cursor)
                if start < 0:
                    raise AccessError('skip_marker_required', 422)
                if start > cursor:
                    regions.append({'kind':'printed','start':cursor,'end':start,'manual_correction':True})
                regions.append(region | {'start': start, 'end': start+len(marker)})
                cursor = start+len(marker)
            if regions and cursor < len(text):
                regions.append({'kind':'printed','start':cursor,'end':len(text),'manual_correction':True})
            # Manual edits have exact text spans; old OCR polygons are not reused as exact new locations.
            updated.append({'page': before['page'], 'text': text, 'regions': regions})
        await session.execute(update(DocumentFile.__table__).where(DocumentFile.document_id == document_id)
                              .values(state='queued', job_id=None, error=None, failure_page=None,
                                      correction_pages=updated, correction_base=base_revision))
        return {'state': 'queued', 'base_revision': base_revision}


async def delete(session, token, document_id):
    from app.sources import switch_source
    async with session.begin():
        await lock_service(session)
        actor = await principal(session, token)
        await owned(session, actor, document_id, write=True)
        await switch_source(session, actor, document_id, deleted=True)
        await session.execute(update(DocumentFile.__table__).where(DocumentFile.document_id == document_id)
                              .values(state='cancelled', job_id=None, correction_pages=null()))
    # Only the explicitly deleted owner's UUID path; never remove source/history rows.
    original_path(document_id).unlink(missing_ok=True)
    return {'deleted': True}
