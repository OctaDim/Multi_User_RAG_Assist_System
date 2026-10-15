import tomllib

from sqlalchemy import insert, select, update

from app.auth import AccessError, lock_service, principal
from app.models import Setting, SettingsAudit
from app.resources import resource_path


def defaults():
    with (resource_path("config") / "runtime.toml").open("rb") as source:
        return tomllib.load(source)


async def current(session):
    row = (await session.execute(select(Setting.__table__).where(Setting.id == 1))).mappings().one()
    config = defaults()
    return {"values": config["generation"] | row["overrides"], "embedding": config["embedding"], "revision": row["revision"], "applied_revision": row["applied_revision"], "mutable": ["max_active", "step_width"]}


async def require_super_admin(session, token):
    actor = await principal(session, token)
    if actor["role"] != "super_admin":
        raise AccessError("forbidden")
    return actor


async def read(session, token):
    async with session.begin():
        await lock_service(session)
        await require_super_admin(session, token)
        return await current(session)


async def write(session, token, changes):
    async with session.begin():
        await lock_service(session, exclusive=True)
        actor = await require_super_admin(session, token)
        if not changes or any(key not in ("max_active", "step_width") or type(value) is not int or value < 1 for key, value in changes.items()):
            raise AccessError("invalid_settings", 422)
        before = await current(session)
        await session.execute(update(Setting.__table__).where(Setting.id == 1).values(
            overrides=Setting.overrides.op('||')(changes), revision=Setting.revision + 1))
        after = await current(session)
        await session.execute(insert(SettingsAudit.__table__).values(
            actor_id=actor["id"], previous=before["values"], updated=after["values"], revision=after["revision"]))
        return after
