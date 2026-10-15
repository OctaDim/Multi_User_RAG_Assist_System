from sqlalchemy import select, func
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
import pytest

from app import answers
from app.auth import AccessError


async def send(session, environment, *, key=None, question="Question", token=None):
    return await answers.admit(
        session,
        token or environment["user"]["token"],
        environment["conversation"],
        key or uuid4(),
        question,
        [environment["document"]],
        environment["tab"],
        environment["proof"],
    )


async def count(connection, table):
    # The table is a constant supplied by these tests, never a request field.
    return (await (await connection.execute(f"SELECT count(*) AS n FROM {table}")).fetchone())["n"]


async def test_concurrent_different_questions_accept_exactly_one(environment, connection, rag_pool):
    ready, start = asyncio.Queue(), asyncio.Event()

    async def competing(question):
        async with rag_pool.connection() as lease, AsyncSession(bind=lease) as independent:
            async with independent.begin():
                pid = await independent.scalar(select(func.pg_backend_pid()))
            await ready.put(pid)
            await start.wait()
            try:
                return await send(independent, environment, question=question)
            except AccessError as error:
                return error

    tasks = [asyncio.create_task(competing(question)) for question in ("First", "Second")]
    pids = [await ready.get(), await ready.get()]
    assert len(set(pids)) == 2
    print("concurrent PostgreSQL connections:", pids)
    start.set()
    outcomes = await asyncio.gather(*tasks)
    assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
    assert [outcome.code for outcome in outcomes if isinstance(outcome, AccessError)] == ["conversation_busy"]
    assert await count(connection, "requests") == 1
    assert await count(connection, "messages") == 1


async def test_lost_ack_is_idempotent_and_a_new_key_is_a_new_operation(session, environment, connection):
    key = uuid4()
    first = await send(session, environment, key=key)
    repeated = await send(session, environment, key=key)
    assert first["id"] == repeated["id"]
    assert await count(connection, "messages") == 1
    await answers.stop(session, environment["user"]["token"], first["id"])
    fresh = await send(session, environment)
    assert fresh["id"] != first["id"]
    assert await count(connection, "messages") == 2


async def test_changed_payload_and_newly_blocked_owner_cannot_reuse_a_key(session, environment, connection):
    key = uuid4()
    await send(session, environment, key=key)
    with pytest.raises(AccessError, match="operation_conflict"):
        await send(session, environment, key=key, question="Changed")
    await connection.execute("UPDATE accounts SET disabled=true WHERE id=%s", (environment["user"]["id"],))
    with pytest.raises(AccessError, match="access_denied"):
        await send(session, environment, key=key)


async def test_no_ready_sources_refuses_without_history_or_late_auto_admission(session, environment, connection):
    await connection.execute("UPDATE documents SET ready=false")
    with pytest.raises(AccessError, match="no_ready_sources"):
        await send(session, environment)
    assert await count(connection, "requests") == await count(connection, "messages") == 0
    await connection.execute("UPDATE documents SET ready=true")
    assert await count(connection, "requests") == 0
    accepted = await send(session, environment)
    assert accepted["state"] == "accepted"


@pytest.mark.parametrize("foreign_role", ["user", "admin"])
async def test_foreign_user_or_admin_cannot_read_or_stop_but_super_admin_can_read(session, environment, connection, foreign_role):
    await connection.execute("UPDATE accounts SET role=%s WHERE id=%s", (foreign_role, environment["admin"]["id"]))
    request = await send(session, environment)
    with pytest.raises(AccessError, match="not_found"):
        await answers.snapshot(session, environment["admin"]["token"], environment["conversation"])
    with pytest.raises(AccessError, match="not_found"):
        await answers.stop(session, environment["admin"]["token"], request["id"])
    history = await answers.snapshot(session, environment["super_admin"]["token"], environment["conversation"])
    assert [message["text"] for message in history["messages"]] == ["Question"]
    with pytest.raises(AccessError, match="not_found"):
        await answers.stop(session, environment["super_admin"]["token"], request["id"])


@pytest.mark.parametrize("flag,value", [("verified", False), ("active", False), ("disabled", True)])
async def test_current_account_state_is_checked_on_every_operation(session, environment, connection, flag, value):
    request = await send(session, environment)
    await connection.execute(f"UPDATE accounts SET {flag}=%s WHERE id=%s", (value, environment["user"]["id"]))
    for operation in (
        send(session, environment),
        answers.snapshot(session, environment["user"]["token"], environment["conversation"]),
        answers.stop(session, environment["user"]["token"], request["id"]),
    ):
        with pytest.raises(AccessError, match="access_denied"):
            await operation


async def test_anonymous_or_expired_session_is_denied(session, environment, connection):
    with pytest.raises(AccessError, match="unauthenticated"):
        await send(session, environment, token="not-a-session")
    await connection.execute("UPDATE sessions SET expires_at=now()-interval '1 second'")
    with pytest.raises(AccessError, match="unauthenticated"):
        await answers.snapshot(session, environment["user"]["token"], environment["conversation"])


async def test_failed_transaction_leaves_no_partial_admission(session, environment, connection, rag_pool):
    await connection.execute("CREATE FUNCTION fail_event() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test rollback'; END $$")
    await connection.execute("CREATE TRIGGER reject_event BEFORE INSERT ON events FOR EACH ROW EXECUTE FUNCTION fail_event()")
    with pytest.raises(DBAPIError) as error:
        await send(session, environment)
    assert error.value.orig.sqlstate == 'P0001'
    for table in ("requests", "messages", "events"):
        assert await count(connection, table) == 0
    await connection.execute("DROP TRIGGER reject_event ON events")
    await send(session, environment)
    async with rag_pool.session() as fresh:
        history = await answers.snapshot(fresh, environment["user"]["token"], environment["conversation"])
        assert [message["text"] for message in history["messages"]] == ["Question"]


@pytest.mark.parametrize('initial', [False, True])
async def test_unavailable_coordinator_refuses_before_admission(session, environment, connection, initial):
    if initial:
        await connection.execute("UPDATE coordinator_lease SET healthy_until='-infinity'")
    else:
        await connection.execute("UPDATE coordinator_lease SET healthy_until=now()-interval '1 second'")
    with pytest.raises(AccessError, match="coordinator_unavailable"):
        await send(session, environment)
    assert await count(connection, "requests") == 0


async def test_database_enforces_occupancy_and_owner_operation_uniqueness(session, environment, connection):
    request = await send(session, environment)
    clone = "INSERT INTO requests(id,conversation_id,owner_id,operation_key,fingerprint,scope,origin_tab,origin_session,state,execution_epoch,context_epoch) SELECT %s,%s,owner_id,%s,fingerprint,scope,origin_tab,origin_session,state,execution_epoch,context_epoch FROM requests WHERE id=%s"
    with pytest.raises(psycopg.errors.UniqueViolation) as occupancy:
        await connection.execute(clone, (uuid4(), environment["conversation"], uuid4(), request["id"]))
    assert occupancy.value.diag.constraint_name == "one_unfinished_request"
    other = uuid4()
    await connection.execute("INSERT INTO conversations(id,owner_id) VALUES (%s,%s)", (other, environment["user"]["id"]))
    with pytest.raises(psycopg.errors.UniqueViolation) as operation:
        await connection.execute(clone, (uuid4(), other, request["operation_key"], request["id"]))
    assert operation.value.diag.constraint_name == "requests_owner_id_operation_key_key"
    assert await count(connection, "requests") == 1
