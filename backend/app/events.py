import asyncio
from datetime import datetime, timedelta, timezone
import secrets
from uuid import uuid4

from app import answers
from app.auth import AccessError, lock_service, principal, secret_hash


GRACE = 10
ACK_TIMEOUT = 15


def now():
    return datetime.now(timezone.utc)


async def lock_tab(connection, actor, tab_id, proof, *, exclusive=False):
    mode = 'UPDATE' if exclusive else 'SHARE'
    tab = await (await connection.execute(
        f'SELECT * FROM tabs WHERE id=%s AND owner_id=%s AND proof_hash=%s FOR {mode}',
        (tab_id, actor['id'], secret_hash(proof)),
    )).fetchone()
    if not tab:
        raise AccessError('invalid_tab')
    return tab


def live(tab):
    return (tab['connection_epoch'] > 0 and tab['connected'] and tab['confirmed']
            and tab['deadline'] is None and tab['ack_until'] is not None and now() < tab['ack_until'])


async def origin(connection, request_id):
    # Same order as admission/deadlines: documents, tab, conversation, request.
    tab = await (await connection.execute(
        'SELECT t.* FROM tabs t JOIN requests r ON r.origin_tab=t.id WHERE r.id=%s FOR SHARE OF t',
        (request_id,),
    )).fetchone()
    current = now()
    deadline = tab['deadline']
    if deadline is None and tab['ack_until'] is not None and current >= tab['ack_until']:
        deadline = tab['ack_until'] + timedelta(seconds=GRACE)
    if deadline is not None and current >= deadline:
        raise AccessError('tab_timeout', 409)


async def create_tab(connection, token):
    proof = secrets.token_urlsafe(32)
    async with connection.transaction():
        await lock_service(connection)
        actor = await principal(connection, token)
        tab = await (await connection.execute(
            'INSERT INTO tabs(id,owner_id,proof_hash) VALUES (%s,%s,%s) RETURNING id',
            (uuid4(), actor['id'], secret_hash(proof)),
        )).fetchone()
    return {**tab, 'proof': proof}


async def settle(connection, tab, current):
    if tab['connected'] and tab['ack_until'] is not None and current >= tab['ack_until']:
        tab = await (await connection.execute(
            'UPDATE tabs SET connected=false,confirmed=false,deadline=coalesce(deadline,ack_until+%s) WHERE id=%s RETURNING *',
            (timedelta(seconds=GRACE), tab['id']),
        )).fetchone()
    if tab['deadline'] is not None and current >= tab['deadline']:
        conversations = await (await connection.execute(
            'SELECT DISTINCT conversation_id FROM requests WHERE origin_tab=%s AND state=ANY(%s) ORDER BY conversation_id',
            (tab['id'], list(answers.UNFINISHED)),
        )).fetchall()
        for row in conversations:
            await connection.execute('SELECT id FROM conversations WHERE id=%s FOR UPDATE', (row['conversation_id'],))
        requests = await (await connection.execute(
            'SELECT * FROM requests WHERE origin_tab=%s AND state=ANY(%s) ORDER BY id FOR UPDATE',
            (tab['id'], list(answers.UNFINISHED)),
        )).fetchall()
        for request in requests:
            await answers.transition(connection, request, 'interrupted', 'tab_timeout')
    return tab


async def connect(connection, token, tab_id, proof):
    challenge = secrets.token_urlsafe(32)
    async with connection.transaction():
        await lock_service(connection)
        actor = await principal(connection, token)
        tab = await lock_tab(connection, actor, tab_id, proof, exclusive=True)
        current = now()
        tab = await settle(connection, tab, current)
        deadline = tab['deadline']
        if deadline is not None and current >= deadline:
            deadline = None  # All old unfinished operations have already expired.
        elif deadline is None and tab['confirmed']:
            deadline = current + timedelta(seconds=GRACE)
        result = await (await connection.execute(
            '''UPDATE tabs SET connection_epoch=connection_epoch+1,connected=true,confirmed=false,
               deadline=%s,ack_until=%s,challenge_hash=%s WHERE id=%s RETURNING id,connection_epoch''',
            (deadline, current + timedelta(seconds=ACK_TIMEOUT), secret_hash(challenge), tab_id),
        )).fetchone()
        return {**result, 'challenge': challenge}


async def ack(connection, token, tab_id, proof, epoch, challenge):
    async with connection.transaction():
        await lock_service(connection)
        actor = await principal(connection, token)
        tab = await lock_tab(connection, actor, tab_id, proof, exclusive=True)
        if tab['connection_epoch'] != epoch:
            raise AccessError('stale_connection', 409)
        current = now()
        if (not tab['connected'] or current >= tab['ack_until']
            or (tab['deadline'] is not None and current >= tab['deadline'])):
            raise AccessError('tab_disconnected', 409)
        if tab['challenge_hash'] != secret_hash(challenge):
            raise AccessError('invalid_heartbeat', 409)
        await connection.execute('UPDATE tabs SET confirmed=true,deadline=NULL,ack_until=%s,challenge_hash=NULL WHERE id=%s',
                                 (current + timedelta(seconds=ACK_TIMEOUT), tab_id))


async def heartbeat(connection, token, tab_id, proof, epoch):
    challenge = secrets.token_urlsafe(32)
    async with connection.transaction():
        await lock_service(connection)
        actor = await principal(connection, token)
        tab = await lock_tab(connection, actor, tab_id, proof, exclusive=True)
        if tab['connection_epoch'] != epoch:
            raise AccessError('stale_connection', 409)
        if (not tab['connected'] or now() >= tab['ack_until']
            or (tab['deadline'] is not None and now() >= tab['deadline'])):
            raise AccessError('tab_disconnected', 409)
        if tab['challenge_hash'] is not None:
            return None
        await connection.execute('UPDATE tabs SET challenge_hash=%s WHERE id=%s', (secret_hash(challenge), tab_id))
        return {'connection_epoch': epoch, 'challenge': challenge}


async def disconnect(connection, token, tab_id, proof, epoch):
    async with connection.transaction():
        await lock_service(connection)
        actor = await principal(connection, token)
        tab = await lock_tab(connection, actor, tab_id, proof, exclusive=True)
        if tab['connection_epoch'] != epoch or not tab['connected']:
            return
        current = now()
        # A delayed close callback cannot extend an already lost heartbeat lease.
        detected = min(current, tab['ack_until'])
        await connection.execute(
            'UPDATE tabs SET connected=false,confirmed=false,deadline=coalesce(deadline,%s) WHERE id=%s',
            (detected + timedelta(seconds=GRACE), tab_id),
        )


async def expire_due(connection):
    current = now()
    due = await (await connection.execute(
        '''SELECT id,owner_id FROM tabs WHERE
           (deadline<=%s AND EXISTS (SELECT 1 FROM requests WHERE origin_tab=tabs.id AND state=ANY(%s)))
           OR (connected AND ack_until<=%s) ORDER BY owner_id,id''',
        (current, list(answers.UNFINISHED), current),
    )).fetchall()
    # One tab per transaction avoids holding A's conversation while waiting on B's
    # tab lock (an admission on B may already be waiting on that conversation).
    for row in due:
        async with connection.transaction():
            await lock_service(connection)
            await connection.execute('SELECT id FROM accounts WHERE id=%s FOR SHARE', (row['owner_id'],))
            tab = await (await connection.execute('SELECT * FROM tabs WHERE id=%s FOR UPDATE', (row['id'],))).fetchone()
            await settle(connection, tab, current)


async def read(connection, token, tab_id, proof, epoch, cursor=None):
    """Authorized committed read boundary; U7 must also fence the actual transport handoff."""
    async with connection.transaction():
        # Event identity is allocated before commit. Wait for every prior writer before
        # capturing the watermark, including concurrent commits in other conversations.
        await lock_service(connection, exclusive=True)
        actor = await principal(connection, token)
        tab = await lock_tab(connection, actor, tab_id, proof)
        if tab['connection_epoch'] != epoch:
            raise AccessError('stale_connection', 409)
        if (not tab['connected'] or now() >= tab['ack_until']
            or (tab['deadline'] is not None and now() >= tab['deadline'])):
            raise AccessError('tab_disconnected', 409)
        watermark = (await (await connection.execute(
            '''SELECT coalesce(max(e.id),0) AS id FROM events e JOIN conversations c ON c.id=e.conversation_id
               WHERE c.owner_id=%s''', (actor['id'],),
        )).fetchone())['id']
        if cursor is None or cursor < 0 or cursor > watermark:
            conversations = await (await connection.execute('SELECT id FROM conversations WHERE owner_id=%s ORDER BY id', (actor['id'],))).fetchall()
            histories = await answers.histories(connection, [value['id'] for value in conversations])
            return {'id': watermark, 'kind': 'snapshot', 'payload': {'conversations': histories}}
        return await (await connection.execute(
            '''SELECT e.* FROM events e JOIN conversations c ON c.id=e.conversation_id
               WHERE c.owner_id=%s AND e.id>%s ORDER BY e.id LIMIT 1''', (actor['id'], cursor),
        )).fetchone()


async def deadlines(pool):
    while True:
        async with pool.connection() as connection:
            await expire_due(connection)
        await asyncio.sleep(0.25)
