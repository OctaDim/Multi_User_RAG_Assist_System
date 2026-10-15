import asyncio
from uuid import uuid4

from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import column, func, select, table, update
import pytest

from app.db import Database


accounts = table("accounts", column("id"), column("paid"))


def checkpoint_payload():
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {"value": {"binary": b"\x00\xff", "items": [1, "two"]}}
    checkpoint["channel_versions"] = {"value": "1"}
    return checkpoint


async def borrowed_saver(session, owner, *, pipeline):
    # The real guard query must establish the physical transaction before saver IO.
    assert (await session.execute(select(accounts.c.id).where(accounts.c.id == owner).with_for_update())).scalar_one() == owner
    connection = await session.connection()
    driver = (await connection.get_raw_connection()).driver_connection
    assert not driver.autocommit
    expected = (await session.execute(select(func.pg_backend_pid(), func.txid_current()))).one()
    actual = await (await driver.execute("SELECT pg_backend_pid(), txid_current()")).fetchone()
    assert tuple(expected) == actual
    saver = AsyncPostgresSaver(driver)
    if pipeline:
        assert saver.supports_pipeline
    else:
        saver.supports_pipeline = False
    return saver


@pytest.mark.parametrize("pipeline", [True, False], ids=["pipeline", "fallback"])
async def test_saver_and_application_rollback_together(environment, pipeline):
    database = Database(environment["dsn"])
    owner = environment["user"]["id"]
    thread_id = uuid4().hex
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    checkpoint = checkpoint_payload()
    try:
        with pytest.raises(RuntimeError, match="after saver"):
            async with database.session() as session, session.begin():
                saver = await borrowed_saver(session, owner, pipeline=pipeline)
                await session.execute(update(accounts).where(accounts.c.id == owner).values(paid=True))
                saved = await saver.aput(config, checkpoint, {"source": "update", "step": 1, "parents": {}}, {"value": "1"})
                await saver.aput_writes(saved, [("value", {"pending": b"\x00\xff"})], "task")
                async with database.connection() as observer:
                    assert database.engine.pool.checkedout() == 2
                    assert await observer.scalar(select(accounts.c.paid).where(accounts.c.id == owner)) is False
                    for name in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                        relation = table(name, column("thread_id"))
                        assert await observer.scalar(select(func.count()).select_from(relation).where(relation.c.thread_id == thread_id)) == 0
                    assert await observer.scalar(select(func.pg_backend_pid())) != await session.scalar(select(func.pg_backend_pid()))
                restored = await saver.aget_tuple(saved)
                assert restored.checkpoint["channel_values"] == checkpoint["channel_values"]
                assert len([item async for item in saver.alist(config)]) == 1
                raise RuntimeError("after saver")
        async with database.connection() as observer:
            assert await observer.scalar(select(accounts.c.paid).where(accounts.c.id == owner)) is False
            for name in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                relation = table(name, column("thread_id"))
                assert await observer.scalar(select(func.count()).select_from(relation).where(relation.c.thread_id == thread_id)) == 0
        assert database.engine.pool.checkedout() == 0
    finally:
        await database.dispose()


@pytest.mark.parametrize("pipeline", [True, False], ids=["pipeline", "fallback"])
async def test_saver_committed_blob_writes_get_list_and_delete(environment, pipeline):
    database = Database(environment["dsn"])
    owner = environment["user"]["id"]
    thread_id = uuid4().hex
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    checkpoint = checkpoint_payload()
    metadata = {"source": "update", "step": 1, "parents": {}}
    try:
        async with database.session() as session, session.begin():
            saver = await borrowed_saver(session, owner, pipeline=pipeline)
            saved = await saver.aput(config, checkpoint, metadata, {"value": "1"})
            await saver.aput_writes(saved, [("value", {"pending": b"\x00\xff"})], "task")
        async with database.session() as session, session.begin():
            saver = await borrowed_saver(session, owner, pipeline=pipeline)
            restored = await saver.aget_tuple(saved)
            assert restored.checkpoint["channel_values"] == checkpoint["channel_values"]
            assert restored.metadata == metadata
            assert restored.pending_writes == [("task", "value", {"pending": b"\x00\xff"})]
            assert [item.config async for item in saver.alist(config)] == [saved]
            await saver.adelete_thread(thread_id)
            assert await session.scalar(select(func.pg_backend_pid())) > 0
        async with database.connection() as observer:
            for name in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                relation = table(name, column("thread_id"))
                assert await observer.scalar(select(func.count()).select_from(relation).where(relation.c.thread_id == thread_id)) == 0
    finally:
        await database.dispose()


async def test_cancelling_blocked_saver_rolls_back_and_releases_guard(environment):
    database = Database(environment["dsn"])
    owner = environment["user"]["id"]
    thread_id = uuid4().hex
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    checkpoint = checkpoint_payload()
    pid_ready = asyncio.get_running_loop().create_future()
    activity = table("pg_stat_activity", column("pid"), column("wait_event_type"))

    async def blocked_operation():
        async with database.session() as session, session.begin():
            saver = await borrowed_saver(session, owner, pipeline=True)
            await session.execute(update(accounts).where(accounts.c.id == owner).values(paid=True))
            pid_ready.set_result(await session.scalar(select(func.pg_backend_pid())))
            await saver.aput(config, checkpoint, {"source": "update", "step": 1, "parents": {}}, {"value": "1"})

    task = None
    try:
        async with database.connection() as blocker, blocker.begin():
            # An uncommitted duplicate checkpoint makes saver wait in its write pipeline.
            driver = (await blocker.get_raw_connection()).driver_connection
            await blocker.execute(select(func.pg_backend_pid()))
            await AsyncPostgresSaver(driver).aput(config, checkpoint, {}, {"value": "1"})
            task = asyncio.create_task(blocked_operation())
            pid = await asyncio.wait_for(pid_ready, 5)
            async with database.connection() as observer:
                async with asyncio.timeout(5):
                    while await observer.scalar(select(activity.c.wait_event_type).where(activity.c.pid == pid)) != "Lock":
                        await observer.rollback()
                        await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
            assert database.engine.pool.checkedout() == 1
            async with database.session() as session, session.begin():
                # NOWAIT proves cancellation released the application guard lock.
                assert await session.scalar(select(accounts.c.paid).where(accounts.c.id == owner).with_for_update(nowait=True)) is False
            await blocker.rollback()
        async with database.session() as session, session.begin():
            saver = await borrowed_saver(session, owner, pipeline=True)
            assert await saver.aget_tuple(config) is None
            assert await session.scalar(select(func.pg_backend_pid())) > 0
        assert database.engine.pool.checkedout() == 0
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await database.dispose()
