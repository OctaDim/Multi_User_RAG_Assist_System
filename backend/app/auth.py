import hashlib


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


async def lock_service(connection, *, exclusive=False):
    mode = "UPDATE" if exclusive else "SHARE"
    return await (await connection.execute(
        f'''SELECT s.id,s.epoch,coalesce(l.healthy_until>clock_timestamp(),false) AS healthy
            FROM service_state s LEFT JOIN coordinator_lease l ON l.id=s.id AND l.epoch=s.epoch
            WHERE s.id=1 FOR {mode} OF s''',
    )).fetchone()


async def principal(connection, token):
    actor = await (await connection.execute(
        "SELECT a.*,s.id AS session_id,s.expires_at AS session_expires_at FROM accounts a JOIN sessions s ON s.owner_id=a.id WHERE s.token_hash=%s AND NOT s.revoked AND s.expires_at>clock_timestamp() FOR SHARE OF a,s",
        (secret_hash(token),),
    )).fetchone()
    if not actor:
        raise AccessError("unauthenticated", 401)
    if not actor["verified"] or not actor["active"] or actor["disabled"]:
        raise AccessError("access_denied")
    return actor


async def originating_session(connection, request_id):
    row = await (await connection.execute(
        '''SELECT a.*,s.id AS session_id,s.revoked,s.expires_at>clock_timestamp() AS session_live
           FROM requests r JOIN accounts a ON a.id=r.owner_id
           JOIN sessions s ON s.id=r.origin_session AND s.owner_id=a.id
           WHERE r.id=%s FOR SHARE OF a,s''', (request_id,),
    )).fetchone()
    if not row or row['revoked'] or not row['session_live']:
        raise AccessError('session_ended', 401)
    if not row['verified'] or not row['active'] or row['disabled']:
        raise AccessError('access_denied')
    return row
