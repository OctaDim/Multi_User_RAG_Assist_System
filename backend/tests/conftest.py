import hashlib
from uuid import uuid4

import pgserver
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
import pytest

from app.db import migrate


async def seed_revision(connection, document_id, *, text="The annual budget is 100 euros.",
                        status="published", upload_complete=True, page_statuses=("ready",),
                        page_count=None, mode="complete", skip_confirmed=False,
                        limitations=None, kind="printed", embedding=None, attach=True):
    """Contract projection fixture, not a real document upload/OCR publisher."""
    from psycopg.types.json import Jsonb

    revision_id, chunk_id = uuid4(), uuid4()
    await connection.execute(
        "INSERT INTO source_revisions VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (revision_id, document_id, status, upload_complete, page_count or len(page_statuses), mode, skip_confirmed, Jsonb(limitations or [])),
    )
    for page, page_status in enumerate(page_statuses, 1):
        await connection.execute("INSERT INTO source_pages VALUES (%s,%s,%s)", (revision_id, page, page_status))
    vector = '[' + ','.join(map(str, embedding or [1.0] + [0.0] * 383)) + ']'
    await connection.execute(
        "INSERT INTO source_chunks(id,revision_id,page,text,span_start,span_end,kind,embedding) VALUES (%s,%s,1,%s,0,%s,%s,%s::vector)",
        (chunk_id, revision_id, text, len(text), kind, vector),
    )
    if attach:
        await connection.execute("UPDATE documents SET published_revision=%s WHERE id=%s", (revision_id, document_id))
    return revision_id, chunk_id


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
        data["revision"], data["chunk"] = await seed_revision(connection, data["document"])
        await connection.execute("INSERT INTO tabs(id,owner_id,proof_hash) VALUES (%s,%s,%s)", (data["tab"], owner, hashlib.sha256(data["proof"].encode()).hexdigest()))
        await connection.execute("UPDATE service_state SET epoch=1 WHERE id=1")
        await connection.execute("UPDATE coordinator_lease SET healthy_until=now()+interval '1 hour',epoch=1 WHERE id=1")
    try:
        yield data
    finally:
        with psycopg.connect(postgres, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
async def connection(environment):
    async with await psycopg.AsyncConnection.connect(environment["dsn"], autocommit=True, row_factory=dict_row) as connection:
        yield connection


@pytest.fixture
async def rag_pool(environment):
    from psycopg_pool import AsyncConnectionPool

    async with AsyncConnectionPool(environment['dsn'], open=False, kwargs={
        'autocommit': True, 'row_factory': dict_row, 'prepare_threshold': 0,
    }) as pool:
        await pool.wait()
        yield pool
