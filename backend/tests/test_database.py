import asyncio
from urllib.parse import quote, urlencode
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from sqlalchemy import column, func, select, table, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
import pytest

from app.db import Database


async def test_database_is_an_explicit_resource_owner():
    first = Database("dbname=resource_owner")
    second = Database("dbname=resource_owner")
    try:
        assert first is not second
        assert first.engine is not second.engine
        async with first.session() as left, first.session() as right:
            assert left is not right
    finally:
        await first.dispose()
        await second.dispose()


async def test_parallel_sessions_use_distinct_connections_and_dispose_closes_pool(postgres):
    database = Database(postgres)
    barrier = asyncio.Barrier(2)
    sessions, drivers = [], []

    async def operation():
        async with database.session() as session:
            assert isinstance(session, AsyncSession)
            sessions.append(session)
            pid = await session.scalar(select(func.pg_backend_pid()))
            connection = await session.connection()
            drivers.append((await connection.get_raw_connection()).driver_connection)
            await asyncio.wait_for(barrier.wait(), 5)
            return pid

    try:
        pids = await asyncio.gather(operation(), operation())
        assert pids[0] != pids[1]
        assert sessions[0] is not sessions[1]
        assert database.engine.pool.checkedout() == 0
        assert all(not driver.closed and not driver.autocommit for driver in drivers)
    finally:
        await database.dispose()
    assert all(driver.closed for driver in drivers)


async def test_session_cleanup_does_not_commit_and_operation_owns_transaction(environment):
    database = Database(environment["dsn"])
    accounts = table("accounts", column("id"), column("paid"))
    account = accounts.c.id == environment["user"]["id"]
    try:
        async with database.session() as session:
            await session.execute(update(accounts).where(account).values(paid=True))
        async with database.session() as observer:
            assert await observer.scalar(select(accounts.c.paid).where(account)) is False
        async with database.session() as session:
            async with session.begin():
                await session.execute(update(accounts).where(account).values(paid=True))
        async with database.session() as observer:
            assert await observer.scalar(select(accounts.c.paid).where(account)) is True
        with pytest.raises(RuntimeError, match="abort operation"):
            async with database.session() as session:
                async with session.begin():
                    await session.execute(update(accounts).where(account).values(paid=False))
                    raise RuntimeError("abort operation")
        async with database.session() as observer:
            assert await observer.scalar(select(accounts.c.paid).where(account)) is True
        assert database.engine.pool.checkedout() == 0
    finally:
        await database.dispose()


@pytest.mark.parametrize("dsn_format", ["conninfo", "uri"])
async def test_socket_options_and_credential_characters_are_preserved(postgres, dsn_format):
    username = "test_'\\:@% " + uuid4().hex
    password = "test-only_'\\:@% /?&="
    parameters = conninfo_to_dict(postgres)
    parameters.update(user=username, password=password, options="-c application_name=database_u1")
    with psycopg.connect(postgres, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
            sql.Identifier(username), sql.Literal(password)))
    if dsn_format == "conninfo":
        dsn = make_conninfo(**parameters)
    else:
        options = {key: value for key, value in parameters.items() if key not in {"user", "password", "dbname"}}
        dsn = (f"postgresql://{quote(username, safe='')}:{quote(password, safe='')}@/"
               f"{quote(parameters.get('dbname', ''), safe='')}?{urlencode(options, quote_via=quote)}")
    database = Database(dsn)
    try:
        # Compare without including either credential in assertion diagnostics.
        assert bool(database.engine.url.username == username)
        assert bool(database.engine.url.password == password)
        assert password not in repr(database.engine)
        async with database.connection() as connection:
            assert isinstance(connection, AsyncConnection)
            row = (await connection.execute(select(func.current_user(), func.current_setting("application_name")))).one()
            assert bool(row[0] == username)
            assert row[1] == "database_u1"
    finally:
        await database.dispose()
        with psycopg.connect(postgres, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(username)))
