import hashlib
import os
from pathlib import Path
import tomllib
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.auth import AccessError, lock_service, principal
from app.resources import resource_path


LIMIT_KEYS = ('file_bytes', 'pdf_pages', 'batch_files', 'documents', 'original_bytes')
PERMISSION_KEYS = ('pdf', 'docx', 'txt', 'md', 'handwriting')
PUBLIC_SQL = '''d.id,d.owner_id,d.ready,d.deleted,f.name,f.format,f.state,f.error,
                f.failure_page,f.declared_bytes,f.original_sha256,f.mode,d.published_revision'''


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


async def initialize_policy(connection, owner_id):
    config = defaults()
    await connection.execute('INSERT INTO document_policies(owner_id,limits,permissions) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
                             (owner_id, Jsonb(config['limits']), Jsonb(config['permissions'])))


async def policy(connection, owner_id, *, exclusive=False):
    if not await (await connection.execute('SELECT id FROM accounts WHERE id=%s', (owner_id,))).fetchone():
        raise AccessError('not_found', 404)
    await initialize_policy(connection, owner_id)
    lock = 'UPDATE' if exclusive else 'SHARE'
    return await (await connection.execute(f'SELECT * FROM document_policies WHERE owner_id=%s FOR {lock}', (owner_id,))).fetchone()


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


async def owned(connection, actor, document_id, *, write=False):
    lock = 'UPDATE' if write else 'SHARE'
    row = await (await connection.execute(
        f'''SELECT {PUBLIC_SQL} FROM documents d JOIN document_files f ON f.document_id=d.id
            WHERE d.id=%s FOR {lock} OF d,f''', (document_id,),
    )).fetchone()
    if not row or row['deleted'] or (row['owner_id'] != actor['id'] and (write or actor['role'] != 'super_admin')):
        raise AccessError('not_found', 404)
    return row


async def admit_uploads(connection, token, files):
    if not files:
        raise AccessError('empty_upload', 422)
    storage()
    async with connection.transaction():
        await lock_service(connection)
        actor = await principal(connection, token)
        config = await policy(connection, actor['id'], exclusive=True)
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
        usage = await (await connection.execute(
            '''SELECT count(*) AS documents,coalesce(sum(f.declared_bytes),0) AS bytes
               FROM document_files f JOIN documents d ON d.id=f.document_id WHERE d.owner_id=%s
               AND NOT d.deleted AND (f.state IN ('receiving','queued','processing','awaiting_choice','ready')
                                     OR f.original_sha256 IS NOT NULL)''', (actor['id'],),
        )).fetchone()
        if usage['documents'] + len(files) > limits['documents'] or usage['bytes'] + sum(f[2] for f in normalized) > limits['original_bytes']:
            raise AccessError('document_storage_limit', 413)
        batch_id, result = uuid4(), []
        for name, extension, size in normalized:
            document_id = uuid4()
            await connection.execute('INSERT INTO documents(id,owner_id) VALUES (%s,%s)', (document_id, actor['id']))
            await connection.execute(
                '''INSERT INTO document_files(document_id,batch_id,name,format,declared_bytes,state,admitted_limits,admitted_handwriting_epoch)
                   VALUES (%s,%s,%s,%s,%s,'receiving',%s,%s)''', (document_id, batch_id, name, extension, size, Jsonb(limits),config['handwriting_epoch']),
            )
            result.append({'id': document_id, 'name': name, 'state': 'receiving', 'ready': False})
        return {'batch_id': batch_id, 'documents': result}


async def fail_upload(connection, document_id, reason, original_digest=None):
    async with connection.transaction():
        await lock_service(connection)
        await connection.execute(
            '''UPDATE document_files SET state=CASE WHEN state='receiving' THEN 'failed' ELSE state END,
               error=CASE WHEN state='receiving' THEN %s ELSE error END,
               original_sha256=coalesce(original_sha256,%s) WHERE document_id=%s''',
            (reason, original_digest, document_id),
        )


async def upload(pool, token, document_id, stream):
    temporary = storage()/f'{document_id}.upload'
    async with pool.connection() as connection, connection.transaction():
        await lock_service(connection)
        actor = await principal(connection, token)
        row = await owned(connection, actor, document_id, write=True)
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
                async with pool.connection() as connection, connection.transaction():
                    await lock_service(connection)
                    actor = await principal(connection, token)
                    config = await policy(connection, actor['id'])
                    current = await owned(connection, actor, document_id, write=True)
                    if current['state'] != 'receiving' or not config['permissions'][row['format']]:
                        raise AccessError('upload_cancelled', 409)
                    output.write(chunk)
                    digest.update(chunk)
            output.flush()
            os.fsync(output.fileno())
        if total != row['declared_bytes']:
            raise AccessError('upload_size_mismatch', 422)
        async with pool.connection() as connection, connection.transaction():
            await lock_service(connection)
            actor = await principal(connection, token)
            config = await policy(connection, actor['id'])
            current = await owned(connection, actor, document_id, write=True)
            if current['state'] != 'receiving' or not config['permissions'][row['format']]:
                raise AccessError('upload_cancelled', 409)
            state = 'awaiting_choice' if row['format'] == 'pdf' and not config['permissions']['handwriting'] else 'queued'
            # link is atomic and refuses to overwrite an existing immutable original.
            os.link(temporary, original_path(document_id))
            linked = True
            temporary.unlink()
            await connection.execute('UPDATE document_files SET state=%s,original_sha256=%s WHERE document_id=%s', (state, digest.hexdigest(), document_id))
            return dict(current, state=state, original_sha256=digest.hexdigest())
    except BaseException as error:
        temporary.unlink(missing_ok=True)
        async with pool.connection() as connection:
            # A missing COMMIT ACK must not delete a potentially committed original.
            await fail_upload(connection, document_id, error.code if isinstance(error, AccessError) else 'upload_failed',
                              digest.hexdigest() if linked else None)
        raise


async def listing(connection, token, owner_id=None):
    async with connection.transaction():
        await lock_service(connection)
        actor = await principal(connection, token)
        owner_id = owner_id or actor['id']
        if owner_id != actor['id'] and actor['role'] != 'super_admin':
            raise AccessError('not_found', 404)
        rows = await (await connection.execute(
            f'''SELECT {PUBLIC_SQL} FROM documents d JOIN document_files f ON f.document_id=d.id
                WHERE d.owner_id=%s AND NOT d.deleted ORDER BY f.created_at,d.id''', (owner_id,),
        )).fetchall()
        return {'documents': rows, 'readonly': owner_id != actor['id']}


async def read(connection, token, document_id):
    async with connection.transaction():
        await lock_service(connection)
        actor = await principal(connection, token)
        row = await owned(connection, actor, document_id)
        if not row['ready']:
            raise AccessError('document_not_ready', 409)
        pages = await (await connection.execute('SELECT page,text,regions FROM document_page_texts WHERE revision_id=%s ORDER BY page', (row['published_revision'],))).fetchall()
        return {'document': row, 'pages': pages}


async def read_original(connection, token, document_id):
    async with connection.transaction():
        await lock_service(connection)
        actor = await principal(connection, token)
        row = await owned(connection, actor, document_id)
        if not row['original_sha256']:
            raise AccessError('original_not_received', 409)
        return row


async def read_policy(connection, token, owner_id):
    async with connection.transaction():
        await lock_service(connection)
        actor = await principal(connection, token)
        if owner_id != actor['id'] and actor['role'] not in ('admin', 'super_admin'):
            raise AccessError('forbidden')
        return await policy(connection, owner_id)


async def update_policy(connection, token, owner_id, value):
    validate_policy(value)
    async with connection.transaction():
        await lock_service(connection, exclusive=True)
        actor = await principal(connection, token)
        if actor['role'] not in ('admin', 'super_admin'):
            raise AccessError('forbidden')
        previous = await policy(connection, owner_id, exclusive=True)
        await connection.execute('UPDATE document_policies SET limits=%s,permissions=%s WHERE owner_id=%s',
                                 (Jsonb(value['limits']), Jsonb(value['permissions']), owner_id))
        revoked = [key for key in PERMISSION_KEYS[:4] if previous['permissions'][key] and not value['permissions'][key]]
        if revoked:
            await connection.execute(
                '''UPDATE document_files f SET state='failed',error='document_permission_revoked',job_id=NULL
                   FROM documents d WHERE d.id=f.document_id AND d.owner_id=%s AND f.format=ANY(%s)
                   AND f.correction_pages IS NULL AND f.state IN ('receiving','queued','processing','awaiting_choice')''', (owner_id, revoked),
            )
        if previous['permissions']['handwriting'] and not value['permissions']['handwriting']:
            await connection.execute('UPDATE document_policies SET handwriting_epoch=handwriting_epoch+1 WHERE owner_id=%s', (owner_id,))
            await connection.execute(
                '''UPDATE document_files f SET state='awaiting_choice',error='handwriting_permission_revoked',job_id=NULL
                   FROM documents d WHERE d.id=f.document_id AND d.owner_id=%s AND f.format='pdf'
                   AND f.mode='complete' AND f.correction_pages IS NULL AND f.state IN ('queued','processing')''', (owner_id,),
            )
        await connection.execute('INSERT INTO document_policy_audit(actor_id,target_id,previous,updated) VALUES (%s,%s,%s,%s)',
                                 (actor['id'], owner_id, Jsonb({'limits': previous['limits'], 'permissions': previous['permissions']}), Jsonb(value)))
        # Workers recheck permissions at every safe page/publication boundary.
        return value


async def choose_mode(connection, token, document_id, choice):
    async with connection.transaction():
        await lock_service(connection)
        actor = await principal(connection, token)
        config = await policy(connection, actor['id'])
        row = await owned(connection, actor, document_id, write=True)
        if row['format'] != 'pdf' or row['state'] not in ('awaiting_choice', 'ready'):
            raise AccessError('document_choice_unavailable', 409)
        if choice == 'cancel':
            if row['ready']:
                raise AccessError('document_choice_unavailable', 409)
            await connection.execute("UPDATE document_files SET state='cancelled',job_id=NULL WHERE document_id=%s", (document_id,))
            return dict(row, state='cancelled')
        if choice not in ('complete', 'skip_handwriting'):
            raise AccessError('invalid_document_mode', 422)
        if not config['permissions']['pdf'] or (choice=='complete' and not config['permissions']['handwriting']):
            raise AccessError('document_permission_revoked')
        limits = config['limits'] if row['ready'] or row['error']=='handwriting_permission_revoked' else None
        if limits and row['declared_bytes'] > limits['file_bytes']:
            raise AccessError('file_size_limit', 413)
        await connection.execute(
            '''UPDATE document_files SET mode=%s,state='queued',job_id=NULL,error=NULL,failure_page=NULL,
               admitted_limits=coalesce(%s,admitted_limits),admitted_handwriting_epoch=%s,
               correction_pages=NULL,correction_base=NULL WHERE document_id=%s''',
            (choice, Jsonb(limits) if limits else None, config['handwriting_epoch'],document_id),
        )
        return dict(row, state='queued', mode=choice)


async def correct(connection, token, document_id, base_revision, pages):
    async with connection.transaction():
        await lock_service(connection)
        actor = await principal(connection, token)
        row = await owned(connection, actor, document_id, write=True)
        if not row['ready'] or row['published_revision'] != base_revision or row['state'] in ('queued','processing'):
            raise AccessError('document_revision_changed', 409)
        previous = await (await connection.execute('SELECT page,text,regions FROM document_page_texts WHERE revision_id=%s ORDER BY page', (base_revision,))).fetchall()
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
        await connection.execute(
            "UPDATE document_files SET state='queued',job_id=NULL,error=NULL,failure_page=NULL,correction_pages=%s,correction_base=%s WHERE document_id=%s",
            (Jsonb(updated), base_revision, document_id),
        )
        return {'state': 'queued', 'base_revision': base_revision}


async def delete(connection, token, document_id):
    from app.sources import switch_source
    async with connection.transaction():
        await lock_service(connection)
        actor = await principal(connection, token)
        await owned(connection, actor, document_id, write=True)
        await switch_source(connection, actor, document_id, deleted=True)
        await connection.execute("UPDATE document_files SET state='cancelled',job_id=NULL,correction_pages=NULL WHERE document_id=%s", (document_id,))
    # Only the explicitly deleted owner's UUID path; never remove source/history rows.
    original_path(document_id).unlink(missing_ok=True)
    return {'deleted': True}
