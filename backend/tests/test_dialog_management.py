from uuid import uuid4
import pytest
from app import answers,accounts,events
from app.auth import AccessError
from test_admission import send


async def test_dialog_dates_follow_creation_and_actual_last_update(session,environment):
    created=await answers.create_conversation(session,environment['user']['token'])
    assert created['created_at'] is not None and created['updated_at']>=created['created_at']
    request=await send(session,environment)
    before=await answers.snapshot(session,environment['user']['token'],environment['conversation'])
    assert before['updated_at']>=before['created_at']
    await answers.stop(session,environment['user']['token'],request['id'])
    after=await answers.snapshot(session,environment['user']['token'],environment['conversation'])
    assert after['created_at']==before['created_at'] and after['updated_at']>before['updated_at']
    me=await accounts.me(session,environment['user']['token'])
    row=next(row for row in me['conversations'] if row['id']==environment['conversation'])
    assert row['created_at']==after['created_at'] and row['updated_at']==after['updated_at']


async def test_delete_dialog_is_owner_only_idempotent_and_keeps_documents(session,environment,connection):
    request=await send(session,environment)
    await answers.stop(session,environment['user']['token'],request['id'])
    for role in ['admin','super_admin']:
        with pytest.raises(AccessError,match='not_found'):
            await answers.delete_conversation(session,environment[role]['token'],environment['conversation'])
    await answers.delete_conversation(session,environment['user']['token'],environment['conversation'])
    await answers.delete_conversation(session,environment['user']['token'],environment['conversation'])
    with pytest.raises(AccessError,match='not_found'):
        await answers.snapshot(session,environment['user']['token'],environment['conversation'])
    with pytest.raises(AccessError,match='not_found'):
        await answers.create_conversation(session,environment['user']['token'],environment['conversation'])
    assert not (await accounts.me(session,environment['user']['token']))['conversations']
    doc=await (await connection.execute('SELECT deleted FROM documents WHERE id=%s',(environment['document'],))).fetchone()
    assert not doc['deleted']
    count=await (await connection.execute("SELECT count(*) AS n FROM events WHERE kind='conversation_deleted'",())).fetchone()
    assert count['n']==1


async def test_active_dialog_cannot_be_deleted_until_stopped(session,environment):
    request=await send(session,environment)
    with pytest.raises(AccessError,match='conversation_busy'):
        await answers.delete_conversation(session,environment['user']['token'],environment['conversation'])
    assert (await answers.snapshot(session,environment['user']['token'],environment['conversation']))['requests'][0]['state']=='accepted'
    await answers.stop(session,environment['user']['token'],request['id'])
    await answers.delete_conversation(session,environment['user']['token'],environment['conversation'])


async def test_deletion_is_fenced_at_snapshot_and_late_event_delivery(session,environment,connection):
    request=await send(session,environment)
    await answers.stop(session,environment['user']['token'],request['id'])
    actor=environment['user'];tab=await (await connection.execute('SELECT connection_epoch FROM tabs WHERE id=%s',(environment['tab'],))).fetchone()
    prepared=await events.read(session,actor['token'],environment['tab'],environment['proof'],tab['connection_epoch'])
    old_event=await (await connection.execute("SELECT * FROM events WHERE request_id=%s AND kind='accepted'",(request['id'],))).fetchone()
    await answers.delete_conversation(session,actor['token'],environment['conversation'])
    async with session.begin():
        from app.auth import principal
        current=await principal(session,actor['token'])
        snapshot=await events.delivery_event(session,current,prepared)
        old=await events.delivery_event(session,current,old_event)
    assert snapshot['payload']['conversations']==[]
    assert snapshot['payload']['deleted_conversation_ids']==[environment['conversation']]
    assert old['kind']=='conversation_deleted' and old['payload']['conversation_id']==str(environment['conversation'])


async def test_concurrent_event_writers_lock_dialog_before_request(environment,connection):
    import asyncio
    from app.db import Database
    from app.generation import Coordinator
    database=Database(environment['dsn'])
    try:
        async with database.session() as session:
            request=await send(session,environment)
        coordinator=Coordinator(database,1,None,None)
        entered=asyncio.Event()
        async def first_writer():
            async with coordinator.guard(request['id']) as (session,row):
                entered.set()
                # Observe the competing transaction actually waiting on a row lock.
                async with asyncio.timeout(3):
                    while True:
                        waiting=await (await connection.execute("SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND pid<>pg_backend_pid() LIMIT 1")).fetchone()
                        if waiting:break
                        await asyncio.sleep(.01)
                await answers.event(session,row,'state',{'state':row['state'],'version':row['version']})
        async def second_writer():
            await entered.wait()
            async with coordinator.guard(request['id']) as (session,row):
                await answers.event(session,row,'state',{'state':row['state'],'version':row['version']})
        await asyncio.wait_for(asyncio.gather(first_writer(),second_writer()),8)
    finally:await database.dispose()
