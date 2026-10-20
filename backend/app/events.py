import asyncio
from datetime import datetime, timedelta, timezone
import secrets
from uuid import uuid4

from sqlalchemy import and_, func, insert, or_, select, update

from app.configuration import load_settings
from app.models import Account, Conversation, Event, Request, Tab
from app import answers
from app.auth import AccessError, lock_service, principal, secret_hash


GRACE = load_settings('policy')['tabs']['grace_seconds']
ACK_TIMEOUT = load_settings('policy')['tabs']['ack_timeout_seconds']


def now():
    return datetime.now(timezone.utc)


async def lock_tab(connection, actor, tab_id, proof, *, exclusive=False):
    tab = (await connection.execute(select(Tab.__table__).where(Tab.id == tab_id, Tab.owner_id == actor["id"], Tab.proof_hash == secret_hash(proof)).with_for_update(read=not exclusive))).mappings().first()
    if not tab:
        raise AccessError('invalid_tab')
    return dict(tab)


def live(tab):
    return (tab['connection_epoch'] > 0 and tab['connected'] and tab['confirmed']
            and tab['deadline'] is None and tab['ack_until'] is not None and now() < tab['ack_until'])


async def origin(connection, request_id):
    # Same order as admission/deadlines: documents, tab, conversation, request.
    tab = (await connection.execute(select(Tab.__table__).join(Request, Request.origin_tab == Tab.id).where(Request.id == request_id).with_for_update(read=True, of=Tab))).mappings().first()
    current = now()
    deadline = tab['deadline']
    if deadline is None and tab['ack_until'] is not None and current >= tab['ack_until']:
        deadline = tab['ack_until'] + timedelta(seconds=GRACE)
    if deadline is not None and current >= deadline:
        raise AccessError('tab_timeout', 409)


async def create_tab(connection, token):
    proof = secrets.token_urlsafe(load_settings('policy')['security']['token_bytes'])
    async with connection.begin():
        await lock_service(connection)
        actor = await principal(connection, token)
        tab = (await connection.execute(insert(Tab.__table__).values(id=uuid4(), owner_id=actor["id"], proof_hash=secret_hash(proof)).returning(Tab.id))).mappings().first()
    return {**tab, 'proof': proof}


async def settle(connection, tab, current):
    if tab['connected'] and tab['ack_until'] is not None and current >= tab['ack_until']:
        tab = (await connection.execute(update(Tab.__table__).where(Tab.id == tab["id"]).values(connected=False, confirmed=False, deadline=func.coalesce(Tab.deadline, Tab.ack_until + timedelta(seconds=GRACE))).returning(Tab.__table__))).mappings().first()
    if tab['deadline'] is not None and current >= tab['deadline']:
        conversations = (await connection.execute(select(Request.conversation_id).where(Request.origin_tab == tab["id"], Request.state.in_(answers.UNFINISHED)).distinct().order_by(Request.conversation_id))).mappings().all()
        for row in conversations:
            await connection.execute(select(Conversation.id).where(Conversation.id == row["conversation_id"]).with_for_update())
        requests = (await connection.execute(select(Request.__table__).where(Request.origin_tab == tab["id"], Request.state.in_(answers.UNFINISHED)).order_by(Request.id).with_for_update())).mappings().all()
        for request in requests:
            await answers.transition(connection, request, 'interrupted', 'tab_timeout')
    return dict(tab)


async def connect(connection, token, tab_id, proof):
    challenge = secrets.token_urlsafe(load_settings('policy')['security']['token_bytes'])
    async with connection.begin():
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
        result = (await connection.execute(update(Tab.__table__).where(Tab.id == tab_id).values(connection_epoch=Tab.connection_epoch + 1, connected=True, confirmed=False, deadline=deadline, ack_until=current + timedelta(seconds=ACK_TIMEOUT), challenge_hash=secret_hash(challenge)).returning(Tab.id, Tab.connection_epoch))).mappings().first()
        return {**result, 'challenge': challenge}


async def ack(connection, token, tab_id, proof, epoch, challenge):
    async with connection.begin():
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
        await connection.execute(update(Tab.__table__).where(Tab.id == tab_id).values(confirmed=True, deadline=None, ack_until=current + timedelta(seconds=ACK_TIMEOUT), challenge_hash=None))


async def heartbeat(connection, token, tab_id, proof, epoch):
    challenge = secrets.token_urlsafe(load_settings('policy')['security']['token_bytes'])
    async with connection.begin():
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
        await connection.execute(update(Tab.__table__).where(Tab.id == tab_id).values(challenge_hash=secret_hash(challenge)))
        return {'connection_epoch': epoch, 'challenge': challenge}


async def disconnect(connection, token, tab_id, proof, epoch):
    async with connection.begin():
        await lock_service(connection)
        actor = await principal(connection, token)
        tab = await lock_tab(connection, actor, tab_id, proof, exclusive=True)
        if tab['connection_epoch'] != epoch or not tab['connected']:
            return
        current = now()
        # A delayed close callback cannot extend an already lost heartbeat lease.
        detected = min(current, tab['ack_until'])
        await connection.execute(update(Tab.__table__).where(Tab.id == tab_id).values(connected=False, confirmed=False, deadline=func.coalesce(Tab.deadline, detected + timedelta(seconds=GRACE))))


async def expire_due(connection):
    current = now()
    async with connection.begin():
        due = (await connection.execute(select(Tab.id, Tab.owner_id).where(or_(and_(Tab.deadline <= current, select(Request.id).where(Request.origin_tab == Tab.id, Request.state.in_(answers.UNFINISHED)).exists()), and_(Tab.connected, Tab.ack_until <= current))).order_by(Tab.owner_id, Tab.id))).mappings().all()
    # One tab per transaction avoids holding A's conversation while waiting on B's
    # tab lock (an admission on B may already be waiting on that conversation).
    for row in due:
        async with connection.begin():
            await lock_service(connection)
            await connection.execute(select(Account.id).where(Account.id == row["owner_id"]).with_for_update(read=True))
            tab = (await connection.execute(select(Tab.__table__).where(Tab.id == row["id"]).with_for_update())).mappings().first()
            await settle(connection, tab, current)


async def read(connection, token, tab_id, proof, epoch, cursor=None):
    """Authorized committed read boundary; U7 must also fence the actual transport handoff."""
    async with connection.begin():
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
        watermark = ((await connection.execute(select(func.coalesce(func.max(Event.id), 0).label("id")).join(Conversation, Conversation.id == Event.conversation_id).where(Conversation.owner_id == actor["id"]))).mappings().first())['id']
        if cursor is None or cursor < 0 or cursor > watermark:
            conversations = (await connection.execute(select(Conversation.id).where(Conversation.owner_id == actor["id"], Conversation.deleted_at.is_(None)).order_by(Conversation.id))).mappings().all()
            histories = await answers.histories(connection, [value['id'] for value in conversations])
            deleted = (await connection.execute(select(Conversation.id).where(Conversation.owner_id == actor['id'], Conversation.deleted_at.is_not(None)).order_by(Conversation.id))).scalars().all()
            return {'id': watermark, 'kind': 'snapshot', 'payload': {'conversations': histories, 'deleted_conversation_ids': deleted}}
        value = (await connection.execute(select(Event.__table__).join(Conversation, Conversation.id == Event.conversation_id).where(Conversation.owner_id == actor["id"], Event.id > cursor).order_by(Event.id).limit(1))).mappings().first()
        return dict(value) if value else None


async def delivery_tab(connection, token, tab_id, proof, epoch):
    actor = await principal(connection, token)
    tab = await lock_tab(connection, actor, tab_id, proof)
    if tab['connection_epoch'] != epoch:
        raise AccessError('stale_connection', 409)
    if (not tab['connected'] or now() >= tab['ack_until']
        or (tab['deadline'] is not None and now() >= tab['deadline'])):
        raise AccessError('tab_disconnected', 409)
    return dict(tab)


async def delivery_event(connection, actor, prepared):
    """Refresh committed delivery inside the transport barrier; cursor stays stable."""
    if prepared['kind'] == 'heartbeat':
        return prepared
    if prepared['kind'] == 'snapshot':
        conversations = (await connection.execute(select(Conversation.id).where(Conversation.owner_id == actor["id"], Conversation.deleted_at.is_(None)).order_by(Conversation.id))).mappings().all()
        watermark = ((await connection.execute(select(func.coalesce(func.max(Event.id), 0).label("id")).join(Conversation, Conversation.id == Event.conversation_id).where(Conversation.owner_id == actor["id"]))).mappings().first())['id']
        deleted = (await connection.execute(select(Conversation.id).where(Conversation.owner_id == actor['id'], Conversation.deleted_at.is_not(None)).order_by(Conversation.id))).scalars().all()
        return {'id':watermark, 'kind':'snapshot', 'payload':{'conversations':await answers.histories(connection,[row['id'] for row in conversations]), 'deleted_conversation_ids': deleted}}
    value = (await connection.execute(select(Event.__table__).join(Conversation, Conversation.id == Event.conversation_id).where(Event.id == prepared["id"], Conversation.owner_id == actor["id"]))).mappings().first()
    if not value:
        raise AccessError('not_found',404)
    deleted = await connection.scalar(select(Conversation.deleted_at).where(Conversation.id == value['conversation_id']))
    if deleted is not None:
        return {**value, 'kind': 'conversation_deleted', 'payload': {'conversation_id': str(value['conversation_id'])}}
    request = (await connection.execute(select(Request.__table__).where(Request.id == value["request_id"]).with_for_update(read=True))).mappings().first()
    from app.sources import source_flags
    flags = await source_flags(connection, request['id'])
    # Old output/fragments are no longer grants to publish after a stop/delete.
    # The preserved history is returned separately with its current labels.
    if value['kind'] in ('output','fragments') and request['state'] in ('interrupted','failed'):
        return {**value, 'kind':'invalidated', 'payload':{'version':request['version'],
            'state':request['state'], 'reason':request['reason'], 'source_flags':flags, 'excluded':True}}
    return {**value, 'payload':{**value['payload'], 'source_flags':flags,
        'excluded':bool(flags) or request['state'] in ('interrupted','failed')}}


async def deadlines(database):
    while True:
        async with database.session() as connection:
            await expire_due(connection)
        await asyncio.sleep(load_settings('policy')['tabs']['sweep_seconds'])
