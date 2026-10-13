import tomllib

from psycopg.types.json import Jsonb

from app.auth import AccessError, lock_service, principal
from app.resources import resource_path


def defaults():
    with (resource_path("config") / "runtime.toml").open("rb") as source:
        return tomllib.load(source)


async def current(connection):
    row = await (await connection.execute("SELECT * FROM settings WHERE id=1")).fetchone()
    config = defaults()
    return {"values": config["generation"] | row["overrides"], "embedding": config["embedding"], "revision": row["revision"], "applied_revision": row["applied_revision"], "mutable": ["max_active", "step_width"]}


async def require_super_admin(connection, token):
    actor = await principal(connection, token)
    if actor["role"] != "super_admin":
        raise AccessError("forbidden")
    return actor


async def read(connection, token):
    async with connection.transaction():
        await lock_service(connection)
        await require_super_admin(connection, token)
        return await current(connection)


async def write(connection, token, changes):
    async with connection.transaction():
        await lock_service(connection, exclusive=True)
        actor = await require_super_admin(connection, token)
        if not changes or any(key not in ("max_active", "step_width") or type(value) is not int or value < 1 for key, value in changes.items()):
            raise AccessError("invalid_settings", 422)
        before = await current(connection)
        await connection.execute("UPDATE settings SET overrides=overrides || %s,revision=revision+1 WHERE id=1", (Jsonb(changes),))
        after = await current(connection)
        await connection.execute("INSERT INTO settings_audit(actor_id,previous,updated,revision) VALUES (%s,%s,%s,%s)", (actor["id"], Jsonb(before["values"]), Jsonb(after["values"]), after["revision"]))
        return after
