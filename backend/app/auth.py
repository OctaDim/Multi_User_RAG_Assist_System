import hashlib

from sqlalchemy import and_, func, select

from app.models import Account, CoordinatorLease, Request, ServiceState, Session


class AccessError(Exception):
    def __init__(self, code, status=403):
        super().__init__(code)
        self.code = code
        self.status = status


def secret_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def bearer(authorization):
    if not authorization or not authorization.startswith("Bearer "):
        raise AccessError("unauthenticated", 401)
    return authorization[7:]


async def lock_service(session, *, exclusive=False):
    row = (await session.execute(
        select(ServiceState.id, ServiceState.epoch,
               func.coalesce(CoordinatorLease.healthy_until > func.clock_timestamp(), False).label('healthy'))
        .outerjoin(CoordinatorLease, and_(CoordinatorLease.id == ServiceState.id,
                                         CoordinatorLease.epoch == ServiceState.epoch))
        .where(ServiceState.id == 1)
        .with_for_update(read=not exclusive, of=ServiceState)
    )).mappings().first()
    return dict(row) if row else None


async def principal(session, token):
    actor = (await session.execute(
        select(Account.__table__, Session.id.label('session_id'),
               Session.expires_at.label('session_expires_at'))
        .join(Session, Session.owner_id == Account.id)
        .where(Session.token_hash == secret_hash(token), ~Session.revoked,
               Session.expires_at > func.clock_timestamp())
        .with_for_update(read=True, of=[Account, Session])
    )).mappings().first()
    if not actor:
        raise AccessError("unauthenticated", 401)
    if not actor["verified"] or not actor["active"] or actor["disabled"]:
        raise AccessError("access_denied")
    return dict(actor)


async def originating_session(session, request_id):
    row = (await session.execute(
        select(Account.__table__, Session.id.label('session_id'), Session.revoked,
               (Session.expires_at > func.clock_timestamp()).label('session_live'))
        .select_from(Request)
        .join(Account, Account.id == Request.owner_id)
        .join(Session, and_(Session.id == Request.origin_session, Session.owner_id == Account.id))
        .where(Request.id == request_id)
        .with_for_update(read=True, of=[Account, Session])
    )).mappings().first()
    if not row or row['revoked'] or not row['session_live']:
        raise AccessError('session_ended', 401)
    if not row['verified'] or not row['active'] or row['disabled']:
        raise AccessError('access_denied')
    return dict(row)
