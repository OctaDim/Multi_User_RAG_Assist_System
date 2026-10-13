import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from app import answers
from app.auth import AccessError
from test_admission import send


async def test_admission_requires_confirmed_connection(environment, connection):
    await connection.execute('UPDATE tabs SET connection_epoch=0 WHERE id=%s', (environment['tab'],))
    with pytest.raises(AccessError, match='tab_disconnected'):
        await send(connection, environment)


@pytest.fixture
async def presence(environment, connection, monkeypatch):
    from app import events
    clock = [datetime.now(timezone.utc)]
    monkeypatch.setattr(events, 'now', lambda: clock[0])
    token = environment['user']['token']
    async def connect(tab=None, proof=None):
        row = await events.connect(connection, token, tab or environment['tab'], proof or environment['proof'])
        await events.ack(connection, token, row['id'], proof or environment['proof'], row['connection_epoch'], row['challenge'])
        return row
    tab = await connect()
    return events, clock, token, connect, tab


async def test_idle_expired_tab_lock_does_not_delay_another_origin_deadline(environment, connection, presence):
    import psycopg
    from psycopg.rows import dict_row
    events, clock, token, connect, tab = presence
    request = await send(connection, environment)
    await events.disconnect(connection, token, tab['id'], environment['proof'], tab['connection_epoch'])
    clock[0] += timedelta(seconds=11)
    idle = UUID(int=0)
    old_deadline = clock[0] - timedelta(seconds=20)
    await connection.execute('INSERT INTO tabs(id,owner_id,proof_hash,deadline) VALUES (%s,%s,%s,%s)',
                             (idle, environment['user']['id'], 'idle', old_deadline))
    async with await psycopg.AsyncConnection.connect(environment['dsn'], autocommit=True, row_factory=dict_row) as locked:
        async with locked.transaction():
            await locked.execute('SELECT id FROM tabs WHERE id=%s FOR UPDATE', (idle,))
            expiry = asyncio.create_task(events.expire_due(connection))
            try:
                await asyncio.wait_for(asyncio.shield(expiry), 3)
            finally:
                if not expiry.done():
                    expiry.cancel()
                await asyncio.gather(expiry, return_exceptions=True)
    stored = (await answers.snapshot(connection, token, environment['conversation']))['requests'][0]
    assert stored['id'] == request['id'] and stored['state'] == 'interrupted'
    assert stored['reason'] == 'tab_timeout'
    assert (await (await connection.execute('SELECT deadline FROM tabs WHERE id=%s', (idle,))).fetchone())['deadline'] == old_deadline


async def test_owner_snapshot_preserves_multiple_and_empty_conversations(environment, connection, presence):
    events, clock, token, connect, tab = presence
    first = await send(connection, environment)
    second_id, empty_id, foreign_id = uuid4(), uuid4(), uuid4()
    for conversation_id, owner in [(second_id, environment['user']['id']), (empty_id, environment['user']['id']),
                                   (foreign_id, environment['admin']['id'])]:
        await connection.execute('INSERT INTO conversations(id,owner_id) VALUES (%s,%s)', (conversation_id, owner))
    second = await answers.admit(connection, token, second_id, uuid4(), 'Second question',
                                 [environment['document']], tab['id'], environment['proof'])
    accepted_ids = {row['conversation_id']: row['id'] for row in await (await connection.execute('SELECT id,conversation_id FROM events')).fetchall()}
    async with connection.transaction():
        from app.auth import lock_service
        await lock_service(connection)
        await connection.execute('SELECT id FROM conversations WHERE id=%s FOR UPDATE', (first['conversation_id'],))
        await connection.execute('UPDATE requests SET answer_text=%s,version=version+1 WHERE id=%s', ('Saved prefix', first['id']))
        await connection.execute("INSERT INTO messages(request_id,conversation_id,role,text) VALUES (%s,%s,'assistant',%s)",
                                 (first['id'], first['conversation_id'], 'Saved prefix'))
        output = await answers.event(connection, first, 'output', {'text': 'Saved prefix', 'version': 2})
    value = await events.read(connection, token, tab['id'], environment['proof'], tab['connection_epoch'])
    histories = value['payload']['conversations']
    assert [history['conversation_id'] for history in histories] == sorted([first['conversation_id'], second_id, empty_id])
    by_id = {history['conversation_id']: history for history in histories}
    assert [(message['role'], message['text']) for message in by_id[first['conversation_id']]['messages']] == [('user', 'Question'), ('assistant', 'Saved prefix')]
    assert [(message['role'], message['text']) for message in by_id[second_id]['messages']] == [('user', 'Second question')]
    assert by_id[empty_id] == {'conversation_id': empty_id, 'messages': [], 'requests': [], 'watermark': 0}
    assert [(row['id'], row['answer_text']) for row in by_id[first['conversation_id']]['requests']] == [(first['id'], 'Saved prefix')]
    assert [(row['id'], row['answer_text']) for row in by_id[second_id]['requests']] == [(second['id'], '')]
    assert by_id[first['conversation_id']]['watermark'] == value['id'] == output['id']
    assert by_id[second_id]['watermark'] == accepted_ids[second_id]


@pytest.mark.parametrize('state', ['accepted', 'searching', 'queued', 'generating'])
async def test_recovery_preserves_same_operation_and_stale_disconnect_is_harmless(environment, connection, presence, state):
    events, clock, token, connect, tab = presence
    request = await send(connection, environment)
    await connection.execute('UPDATE requests SET state=%s WHERE id=%s', (state, request['id']))
    await events.disconnect(connection, token, tab['id'], environment['proof'], tab['connection_epoch'])
    clock[0] += timedelta(seconds=5)
    recovered = await connect()
    assert recovered['connection_epoch'] > tab['connection_epoch']
    await events.disconnect(connection, token, tab['id'], environment['proof'], tab['connection_epoch'])
    clock[0] += timedelta(seconds=6)
    await events.expire_due(connection)
    stored = (await answers.snapshot(connection, token, environment['conversation']))['requests'][0]
    assert stored['id'] == request['id'] and stored['state'] == state
    assert (await (await connection.execute('SELECT started FROM graph_bindings')).fetchone())['started'] is False
    assert (await (await connection.execute('SELECT count(*) n FROM messages')).fetchone())['n'] == 1


@pytest.mark.parametrize('state', ['accepted', 'searching', 'generating'])
async def test_observer_cannot_extend_deadline_and_late_recovery_cannot_rescue(environment, connection, presence, state):
    events, clock, token, connect, tab = presence
    request = await send(connection, environment)
    await connection.execute('UPDATE requests SET state=%s WHERE id=%s', (state, request['id']))
    observer = await events.create_tab(connection, token)
    other = await connect(observer['id'], observer['proof'])
    await events.disconnect(connection, token, tab['id'], environment['proof'], tab['connection_epoch'])
    clock[0] += timedelta(seconds=11)
    heartbeat = await events.heartbeat(connection, token, other['id'], observer['proof'], other['connection_epoch'])
    await events.ack(connection, token, other['id'], observer['proof'], other['connection_epoch'], heartbeat['challenge'])
    await connect()  # Expiry is mandatory even before the deadline worker ran.
    snapshot = await answers.snapshot(connection, token, environment['conversation'])
    assert snapshot['requests'][0]['state'] == 'interrupted'
    assert snapshot['requests'][0]['reason'] == 'tab_timeout'
    assert (await (await connection.execute('SELECT started FROM graph_bindings')).fetchone())['started'] is False
    with pytest.raises(AccessError, match='terminal_request'):
        from app.rag import GuardedSaver
        binding = await (await connection.execute('SELECT * FROM graph_bindings')).fetchone()
        from psycopg_pool import AsyncConnectionPool
        async with AsyncConnectionPool(environment['dsn'], open=False, kwargs={'autocommit': True, 'row_factory': __import__('psycopg').rows.dict_row}) as pool:
            await pool.wait()
            async with GuardedSaver(pool, binding).guard():
                pass


@pytest.mark.parametrize('terminal,reason', [('completed', 'finished'), ('failed', 'generation_error'), ('interrupted', 'user_stop')])
async def test_terminal_during_grace_is_immediate_and_survives_timeout(environment, connection, presence, terminal, reason):
    events, clock, token, connect, tab = presence
    request = await send(connection, environment)
    await events.disconnect(connection, token, tab['id'], environment['proof'], tab['connection_epoch'])
    clock[0] += timedelta(seconds=6)
    if terminal == 'interrupted':
        await answers.stop(connection, token, request['id'])
    else:
        async with connection.transaction():
            await connection.execute('SELECT id FROM conversations WHERE id=%s FOR UPDATE', (environment['conversation'],))
            await answers.transition(connection, request, terminal, reason)
    assert (await answers.snapshot(connection, token, environment['conversation']))['requests'][0]['state'] == terminal
    clock[0] += timedelta(seconds=6)
    await events.expire_due(connection)
    await connect()
    assert (await answers.snapshot(connection, token, environment['conversation']))['requests'][0]['state'] == terminal


async def test_background_conversations_and_missing_heartbeat_ack(environment, connection, presence):
    events, clock, token, connect, tab = presence
    first = await send(connection, environment)
    second_conversation = uuid4()
    await connection.execute('INSERT INTO conversations(id,owner_id) VALUES (%s,%s)', (second_conversation, environment['user']['id']))
    second = await answers.admit(connection, token, second_conversation, uuid4(), 'Background B', [environment['document']], tab['id'], environment['proof'])
    await answers.snapshot(connection, token, second_conversation)  # Navigation changes no presence.
    clock[0] += timedelta(seconds=4)
    await events.ack(connection, token, tab['id'], environment['proof'], tab['connection_epoch'], (await events.heartbeat(connection, token, tab['id'], environment['proof'], tab['connection_epoch']))['challenge'])
    await events.expire_due(connection)
    assert {r['state'] for r in await (await connection.execute('SELECT state FROM requests')).fetchall()} == {'accepted'}
    clock[0] += timedelta(seconds=events.ACK_TIMEOUT + 11)
    await events.expire_due(connection)
    assert {r['state'] for r in await (await connection.execute('SELECT state FROM requests')).fetchall()} == {'interrupted'}


async def test_proof_owner_and_epoch_checks(environment, connection, presence):
    events, clock, token, connect, tab = presence
    for foreign_token, proof in [(environment['admin']['token'], environment['proof']), (token, 'wrong')]:
        with pytest.raises(AccessError, match='invalid_tab'):
            await events.connect(connection, foreign_token, tab['id'], proof)
    recovered = await connect()
    with pytest.raises(AccessError, match='stale_connection'):
        await events.ack(connection, token, tab['id'], environment['proof'], tab['connection_epoch'], tab['challenge'])
    await events.disconnect(connection, token, tab['id'], environment['proof'], tab['connection_epoch'])
    assert (await events.read(connection, token, tab['id'], environment['proof'], recovered['connection_epoch']))['kind'] == 'snapshot'


async def test_snapshot_replay_monotonic_and_access_rechecked(environment, connection, presence):
    events, clock, token, connect, tab = presence
    request = await send(connection, environment)
    snapshot = await events.read(connection, token, tab['id'], environment['proof'], tab['connection_epoch'])
    cursor = snapshot['id']
    assert snapshot['payload']['conversations'][0]['requests'][0]['id'] == request['id']
    async with connection.transaction():
        await connection.execute('SELECT id FROM conversations WHERE id=%s FOR UPDATE', (environment['conversation'],))
        await connection.execute("UPDATE requests SET answer_text='Hello',version=version+1 WHERE id=%s", (request['id'],))
        await answers.event(connection, request, 'delta', {'text': 'Hello', 'version': 2})
    delta = await events.read(connection, token, tab['id'], environment['proof'], tab['connection_epoch'], cursor)
    assert delta['id'] > cursor and delta['payload']['text'] == 'Hello'
    assert delta['conversation_id'] == environment['conversation']
    assert await events.read(connection, token, tab['id'], environment['proof'], tab['connection_epoch'], delta['id']) is None
    await connection.execute('UPDATE sessions SET revoked=true WHERE token_hash=(SELECT token_hash FROM sessions WHERE owner_id=%s)', (environment['user']['id'],))
    with pytest.raises(AccessError, match='unauthenticated'):
        await events.read(connection, token, tab['id'], environment['proof'], tab['connection_epoch'], cursor)


@pytest.mark.parametrize('read_tab', [False, True])
async def test_snapshot_watermark_waits_for_lower_uncommitted_event(environment, connection, presence, read_tab):
    import psycopg
    from psycopg.rows import dict_row
    from app.auth import lock_service
    events, clock, token, connect, tab = presence
    first = await send(connection, environment)
    conversation = uuid4()
    await connection.execute('INSERT INTO conversations(id,owner_id) VALUES (%s,%s)', (conversation, environment['user']['id']))
    second = await answers.admit(connection, token, conversation, uuid4(), 'Second', [environment['document']], tab['id'], environment['proof'])
    async with await psycopg.AsyncConnection.connect(environment['dsn'], autocommit=True, row_factory=dict_row) as lower, await psycopg.AsyncConnection.connect(environment['dsn'], autocommit=True, row_factory=dict_row) as higher:
        async with lower.transaction():
            await lock_service(lower)
            lower_id = (await answers.event(lower, first, 'output', {'text': 'lower', 'version': 2}))['id']
            async with higher.transaction():
                await lock_service(higher)
                higher_id = (await answers.event(higher, second, 'output', {'text': 'higher', 'version': 2}))['id']
            assert higher_id > lower_id
            if read_tab:
                task = asyncio.create_task(events.read(connection, token, tab['id'], environment['proof'], tab['connection_epoch']))
            else:
                task = asyncio.create_task(answers.snapshot(connection, token, environment['conversation']))
            pid = (await (await lower.execute('SELECT pg_backend_pid() pid')).fetchone())['pid']
            # Observe the real service lock wait, without a logical grace sleep.
            for _ in range(100):
                blocked = await (await higher.execute("SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND pid<>%s", (pid,))).fetchone()
                if blocked:
                    break
                await asyncio.sleep(0.01)
            assert blocked and not task.done()
        snapshot = await asyncio.wait_for(task, 3)
    if read_tab:
        assert snapshot['id'] == higher_id
        assert await events.read(connection, token, tab['id'], environment['proof'], tab['connection_epoch'], higher_id) is None
        replay = await events.read(connection, token, tab['id'], environment['proof'], tab['connection_epoch'], lower_id - 1)
        assert replay['id'] == lower_id
        # Redelivery repeats an immutable event ID, allowing U6 to ignore duplicates.
        assert await events.read(connection, token, tab['id'], environment['proof'], tab['connection_epoch'], lower_id - 1) == replay
    else:
        assert snapshot['watermark'] == lower_id


async def test_heartbeat_challenge_is_one_use_and_unconfirmed_reconnect_refuses_new_admission(environment, connection, presence):
    events, clock, token, connect, tab = presence
    raw = await events.connect(connection, token, tab['id'], environment['proof'])
    with pytest.raises(AccessError, match='tab_disconnected'):
        await send(connection, environment)
    with pytest.raises(AccessError, match='invalid_heartbeat'):
        await events.ack(connection, token, tab['id'], environment['proof'], raw['connection_epoch'], 'guessed')
    await events.ack(connection, token, tab['id'], environment['proof'], raw['connection_epoch'], raw['challenge'])
    with pytest.raises(AccessError, match='invalid_heartbeat'):
        await events.ack(connection, token, tab['id'], environment['proof'], raw['connection_epoch'], raw['challenge'])
    await send(connection, environment)


async def test_same_native_context_continues_through_reconnect_and_dedupe(environment, connection, presence, rag_pool):
    from app.generation import Coordinator
    from test_scheduler import TokenRuntime, settle
    from test_rag_context import ContractEmbedder
    events, clock, token, connect, tab = presence
    key = uuid4()
    request = await send(connection, environment, key=key)
    runtime = TokenRuntime()
    coordinator = Coordinator(rag_pool, 1, runtime, ContractEmbedder())
    try:
        await coordinator.prepare_next()
        await coordinator.admit_ready()
        context = runtime.contexts[request['id']]
        await coordinator.step()
        await events.disconnect(connection, token, tab['id'], environment['proof'], tab['connection_epoch'])
        clock[0] += timedelta(seconds=5)
        await coordinator.step()
        recovered = await connect()
        snapshot = await events.read(connection, token, tab['id'], environment['proof'], recovered['connection_epoch'])
        stored = snapshot['payload']['conversations'][0]['requests'][0]
        assert stored['answer_text'] == 'первый второй '
        assert (await send(connection, environment, key=key))['id'] == request['id']
        assert runtime.contexts[request['id']] is context and len(runtime.contexts) == 1
        await coordinator.step()
        assert (await answers.snapshot(connection, token, environment['conversation']))['requests'][0]['state'] == 'completed'
    finally:
        await answers.stop(connection, token, request['id'])
        await settle(coordinator)


async def test_delayed_search_callback_cannot_publish_after_deadline(environment, connection, presence, rag_pool):
    from app.rag import run_graph
    from test_rag_context import ContractEmbedder
    events, clock, token, connect, tab = presence
    request = await send(connection, environment)
    await connection.execute("UPDATE requests SET state='searching' WHERE id=%s", (request['id'],))
    await events.disconnect(connection, token, tab['id'], environment['proof'], tab['connection_epoch'])
    clock[0] += timedelta(seconds=11)
    with pytest.raises(AccessError, match='tab_timeout'):
        await run_graph(rag_pool, request['id'], 1, ContractEmbedder(), lambda text: list(text.encode()))
    assert (await (await connection.execute("SELECT count(*) n FROM events WHERE kind='fragments'")).fetchone())['n'] == 0
    assert (await (await connection.execute('SELECT started FROM graph_bindings')).fetchone())['started'] is False
    await events.expire_due(connection)
    assert (await answers.snapshot(connection, token, environment['conversation']))['requests'][0]['state'] == 'interrupted'


async def test_unacknowledged_reconnect_does_not_extend_original_grace(environment, connection, presence):
    events, clock, token, connect, tab = presence
    request = await send(connection, environment)
    await events.disconnect(connection, token, tab['id'], environment['proof'], tab['connection_epoch'])
    clock[0] += timedelta(seconds=9)
    raw = await events.connect(connection, token, tab['id'], environment['proof'])
    clock[0] += timedelta(seconds=2)
    with pytest.raises(AccessError, match='tab_disconnected'):
        await events.ack(connection, token, tab['id'], environment['proof'], raw['connection_epoch'], raw['challenge'])
    await events.expire_due(connection)
    assert (await answers.snapshot(connection, token, environment['conversation']))['requests'][0]['state'] == 'interrupted'
    await connect()
    fresh = await send(connection, environment)
    history = await answers.snapshot(connection, token, environment['conversation'])
    assert fresh['id'] != request['id']
    assert [r['state'] for r in history['requests']] == ['interrupted', 'accepted']


@pytest.mark.parametrize('seconds,expected', [(9.5, 'accepted'), (10, 'interrupted')])
async def test_reconnect_and_expiry_race_share_tab_lock(environment, connection, presence, seconds, expected):
    import psycopg
    from psycopg.rows import dict_row
    events, clock, token, connect, tab = presence
    request = await send(connection, environment)
    await events.disconnect(connection, token, tab['id'], environment['proof'], tab['connection_epoch'])
    clock[0] += timedelta(seconds=seconds)
    async with await psycopg.AsyncConnection.connect(environment['dsn'], autocommit=True, row_factory=dict_row) as independent:
        async def recover():
            recovered = await events.connect(connection, token, tab['id'], environment['proof'])
            await events.ack(connection, token, tab['id'], environment['proof'], recovered['connection_epoch'], recovered['challenge'])
        await asyncio.wait_for(asyncio.gather(recover(), events.expire_due(independent)), 3)
    assert (await answers.snapshot(connection, token, environment['conversation']))['requests'][0]['state'] == expected


async def test_actual_tab_sse_confirmed_on_second_api_and_deadline_survives_first_api_death(environment, connection, tmp_path):
    import json
    import os
    from pathlib import Path
    import re
    import subprocess
    from urllib.request import Request, urlopen

    backend = Path(__file__).parents[1]
    processes, logs = [], []
    response = None
    token = environment['user']['token']
    async def launch(name):
        log = tmp_path / (name + '.log')
        handle = log.open('xb')
        logs.append(handle)
        process = subprocess.Popen([str(backend / '.venv/bin/rag-api'), '--port', '0'], cwd=backend,
                                   env=dict(os.environ, RAG_DATABASE_URL=environment['dsn']), stdout=handle, stderr=subprocess.STDOUT)
        processes.append(process)
        for _ in range(200):
            assert process.poll() is None, log.read_text()
            found = re.search(r'Uvicorn running on (http://127\.0\.0\.1:\d+)', log.read_text())
            if found:
                return process, found.group(1)
            await asyncio.sleep(0.025)
        raise AssertionError('API did not start')
    async def http(base, route, payload=None, headers=None):
        def send():
            request_headers = {'Authorization': f'Bearer {token}', **(headers or {})}
            if payload is not None:
                request_headers['Content-Type'] = 'application/json'
            data = json.dumps(payload).encode() if payload is not None else None
            with urlopen(Request(base + route, data=data, headers=request_headers), timeout=5) as result:
                return json.load(result)
        return await asyncio.to_thread(send)
    def read_event():
        while True:
            line = response.readline()
            if not line:
                raise AssertionError('SSE ended')
            if line.startswith(b'data: '):
                return json.loads(line[6:])
    try:
        first_process, first = await launch('first')
        _, second = await launch('second')
        tab = await http(first, '/api/tabs', {})
        headers = {'Authorization': f'Bearer {token}', 'X-Tab-Proof': tab['proof']}
        response = await asyncio.to_thread(urlopen, Request(first + f"/api/tabs/{tab['id']}/events", headers=headers), timeout=5)
        heartbeat = (await asyncio.to_thread(read_event))['payload']
        ack_headers = {'X-Tab-Proof': tab['proof'], 'X-Connection-Epoch': str(heartbeat['connection_epoch']),
                       'X-Heartbeat-Challenge': heartbeat['challenge']}
        assert (await http(second, f"/api/tabs/{tab['id']}/heartbeat", {}, ack_headers))['confirmed']
        question = {'operation_key': str(uuid4()), 'question': 'Actual shared SSE',
                    'document_ids': [str(environment['document'])], 'tab_id': str(tab['id'])}
        admitted = await http(second, f"/api/conversations/{environment['conversation']}/answers", question, {'X-Tab-Proof': tab['proof']})
        observed = await asyncio.to_thread(read_event)
        if observed['kind'] == 'snapshot' and not observed['payload']['conversations'][0]['requests']:
            observed = await asyncio.to_thread(read_event)
        assert observed['kind'] in ('snapshot', 'accepted')
        first_process.kill()
        await asyncio.to_thread(first_process.wait, 5)
        # Advance the durable detection lease rather than sleeping through grace.
        await connection.execute("UPDATE tabs SET ack_until=clock_timestamp()-interval '26 seconds' WHERE id=%s", (tab['id'],))
        for _ in range(100):
            history = await http(second, f"/api/conversations/{environment['conversation']}")
            if history['requests'][0]['state'] == 'interrupted':
                break
            await asyncio.sleep(0.025)
        assert history['requests'][0]['id'] == admitted['id']
        assert history['requests'][0]['reason'] == 'tab_timeout'
        assert (await (await connection.execute('SELECT started FROM graph_bindings')).fetchone())['started'] is False
    finally:
        if response is not None:
            response.close()
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    await asyncio.to_thread(process.wait, 5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait, 5)
        for handle in logs:
            handle.close()
