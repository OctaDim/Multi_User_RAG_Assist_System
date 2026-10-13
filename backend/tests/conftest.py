import hashlib
from uuid import uuid4

import pgserver
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
import pytest

from app.db import migrate


@pytest.fixture(scope="session")
def postgres(tmp_path_factory):
    server = pgserver.get_server(tmp_path_factory.mktemp("postgres"), cleanup_mode="stop")
    try:
        yield server.get_uri()
    finally:
        server.cleanup()


@pytest.fixture
async def environment(postgres):
    name = "test_" + uuid4().hex
    with psycopg.connect(postgres, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = make_conninfo(postgres, dbname=name)
    await migrate(dsn)
    data = {"dsn": dsn, "conversation": uuid4(), "document": uuid4(), "tab": uuid4(), "proof": uuid4().hex}
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as connection:
        for role in ("user", "admin", "super_admin"):
            owner, token = uuid4(), uuid4().hex
            data[role] = {"id": owner, "token": token}
            await connection.execute("INSERT INTO accounts(id, role, verified, active, disabled, paid) VALUES (%s,%s,true,true,false,false)", (owner, role))
            await connection.execute("INSERT INTO sessions(token_hash, owner_id, expires_at) VALUES (%s,%s,now()+interval '1 hour')", (hashlib.sha256(token.encode()).hexdigest(), owner))
        owner = data["user"]["id"]
        await connection.execute("INSERT INTO conversations(id,owner_id) VALUES (%s,%s)", (data["conversation"], owner))
        await connection.execute("INSERT INTO documents(id,owner_id,ready,deleted) VALUES (%s,%s,true,false)", (data["document"], owner))
        await connection.execute("INSERT INTO tabs(id,owner_id,proof_hash) VALUES (%s,%s,%s)", (data["tab"], owner, hashlib.sha256(data["proof"].encode()).hexdigest()))
        await connection.execute("UPDATE service_state SET healthy_until=now()+interval '1 hour', epoch=1 WHERE id=1")
    try:
        yield data
    finally:
        with psycopg.connect(postgres, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
async def connection(environment):
    async with await psycopg.AsyncConnection.connect(environment["dsn"], autocommit=True, row_factory=dict_row) as connection:
        yield connection
