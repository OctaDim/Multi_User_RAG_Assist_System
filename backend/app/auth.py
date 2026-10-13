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
    return await (await connection.execute(f"SELECT *, healthy_until>clock_timestamp() AS healthy FROM service_state WHERE id=1 FOR {mode}")).fetchone()


async def principal(connection, token):
    actor = await (await connection.execute(
        "SELECT a.* FROM accounts a JOIN sessions s ON s.owner_id=a.id WHERE s.token_hash=%s AND NOT s.revoked AND s.expires_at>clock_timestamp() FOR SHARE OF a,s",
        (secret_hash(token),),
    )).fetchone()
    if not actor:
        raise AccessError("unauthenticated", 401)
    if not actor["verified"] or not actor["active"] or actor["disabled"]:
        raise AccessError("access_denied")
    return actor
