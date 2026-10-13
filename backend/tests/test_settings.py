import pytest

from app.auth import AccessError
from app.db import migrate
from app import settings


async def test_saved_overrides_survive_repeated_controlled_migration(environment, connection):
    initial = await settings.read(connection, environment["super_admin"]["token"])
    assert initial["values"]["max_active"] == 12
    saved = await settings.write(connection, environment["super_admin"]["token"], {"max_active": 6})
    assert saved["values"]["max_active"] == 6
    assert saved["revision"] == 1 and saved["applied_revision"] == 0
    await migrate(environment["dsn"])
    restored = await settings.read(connection, environment["super_admin"]["token"])
    assert restored["values"]["max_active"] == 6 and restored["revision"] == 1


@pytest.mark.parametrize("role", ["user", "admin"])
async def test_global_changes_require_super_admin(environment, connection, role):
    with pytest.raises(AccessError, match="forbidden"):
        await settings.write(connection, environment[role]["token"], {"max_active": 6})
    assert (await settings.read(connection, environment["super_admin"]["token"]))["revision"] == 0


@pytest.mark.parametrize("changes", [{"n_ctx": 8192}, {"n_threads": 8}, {"max_active": 0}, {"step_width": True}, {"unknown": 3}])
async def test_restart_only_and_invalid_changes_do_not_change_revision(environment, connection, changes):
    with pytest.raises(AccessError, match="invalid_settings"):
        await settings.write(connection, environment["super_admin"]["token"], changes)
    current = await settings.read(connection, environment["super_admin"]["token"])
    assert current["revision"] == 0 and current["values"]["max_active"] == 12
