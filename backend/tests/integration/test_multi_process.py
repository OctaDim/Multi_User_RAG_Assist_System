"""U4: actual HTTP processes and production coordinator on the pinned local models."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
from time import monotonic
from urllib.request import Request, urlopen
from uuid import uuid4

from conftest import seed_revision
from app.rag import E5Embedder


async def eventually(predicate, timeout=90):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        result = await predicate()
        if result:
            return result
        await asyncio.sleep(0.05)
    raise AssertionError('Expected real process state was not reached')


def traces(path):
    values = []
    for line in path.read_text(errors='replace').splitlines():
        if line.startswith('{"event": "native_'):
            try:
                values.append(json.loads(line))
            except json.JSONDecodeError:  # A concurrently written final line is not yet a trace.
                pass
    return values


def live_contexts(events):
    active = {}
    for event in events:
        if event['event'] == 'native_allocate':
            assert event['request'] not in active
            active[event['request']] = event['context']
            assert event['physical_active'] == len(active)
            assert len(active) <= event['max_active']
        elif event['event'] == 'native_release':
            assert event['request'] in active
            active.pop(event['request'])
            assert event['physical_active'] == len(active)
    return active


async def test_two_http_processes_share_native_capacity_fairness_and_hot_settings(environment, connection, tmp_path):
    model = Path(os.environ['RAG_MODEL_PATH'])
    with model.open('rb') as source:
        assert hashlib.file_digest(source, 'sha256').hexdigest() == 'aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223'
    for asset, digest in (
        ('model_quantized.onnx', 'f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193'),
        ('tokenizer.json', '0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39'),
    ):
        with (Path(os.environ['RAG_E5_DIR']) / asset).open('rb') as source:
            assert hashlib.file_digest(source, 'sha256').hexdigest() == digest
    embedder = E5Embedder(os.environ['RAG_E5_DIR'])
    paragraph = ('The annual budget is 100 euros. The approved annual budget is 100 euros. '
                 'The budget pays for the annual maintenance of the library and its reading rooms. ')
    passage = paragraph * 55
    question = 'What is the approved annual budget for the library and its reading rooms?'
    vector = (await asyncio.to_thread(embedder.encode, [passage]))[0]
    query = (await asyncio.to_thread(embedder.encode, [question], query=True))[0]
    similarity = sum(left * right for left, right in zip(vector, query))
    assert similarity >= 0.75, 'Real fixture passage must meet the unchanged production retrieval threshold'
    revision, chunk = await seed_revision(connection, environment['document'], text=passage, embedding=vector)
    del embedder

    log_directory = Path(os.environ.get('RAG_MULTI_API_EVIDENCE_DIR', tmp_path))
    run_name = os.environ.get('RAG_MULTI_API_RUN_NAME', 'process')
    env = dict(os.environ, RAG_DATABASE_URL=environment['dsn'])
    backend = Path(__file__).parents[2]
    processes, streams, requests = [], [], []
    native_pid = None
    bootstrap = tmp_path / 'trace-generation.py'
    bootstrap.write_text('''import logging
logging.basicConfig(level=logging.DEBUG,format='%(message)s')
logging.getLogger('psycopg').setLevel(logging.WARNING)
logging.getLogger('psycopg.pool').setLevel(logging.WARNING)
from app import generation
original=generation.subprocess.Popen
def spawn(args,**kwargs):
    if '--worker' in args:
        args=[args[0],__file__,*args[3:]]
    return original(args,**kwargs)
generation.subprocess.Popen=spawn
generation.main()
''')

    def launch(name, command):
        path = log_directory / f'{run_name}-{name}.log'
        stream = path.open('xb')
        streams.append(stream)
        process = subprocess.Popen(command, cwd=backend, env=env, stdout=stream, stderr=subprocess.STDOUT)
        processes.append(process)
        return process, path

    async def stop_process(process):
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                await asyncio.to_thread(process.wait, 15)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait, 10)

    async def api(name):
        process, log = launch(name, [str(backend / '.venv/bin/rag-api'), '--port', '0'])

        async def listening():
            assert process.poll() is None, log.read_text(errors='replace')
            found = re.search(r'Uvicorn running on (http://127\.0\.0\.1:\d+)', log.read_text(errors='replace'))
            return found.group(1) if found else None

        return process, await eventually(listening, 20)

    async def http(base, method, route, token, payload=None, proof=None, *, consume_ack=True):
        def send():
            headers = {'Authorization': f'Bearer {token}'}
            if payload is not None:
                headers['Content-Type'] = 'application/json'
            if proof:
                headers['X-Tab-Proof'] = proof
            body = json.dumps(payload).encode() if payload is not None else None
            with urlopen(Request(base + route, data=body, headers=headers, method=method), timeout=10) as response:
                assert response.status == 200
                return json.load(response) if consume_ack else None
        return await asyncio.to_thread(send)

    async def submit(base, *, lose_ack=False):
        conversation, tab, operation, proof = uuid4(), uuid4(), uuid4(), uuid4().hex
        await connection.execute('INSERT INTO conversations(id,owner_id) VALUES (%s,%s)', (conversation, environment['user']['id']))
        await connection.execute('INSERT INTO tabs(id,owner_id,proof_hash) VALUES (%s,%s,%s)',
                                 (tab, environment['user']['id'], hashlib.sha256(proof.encode()).hexdigest()))
        payload = {'operation_key': str(operation), 'question': question,
                   'document_ids': [str(environment['document'])], 'tab_id': str(tab)}
        route = f'/api/conversations/{conversation}/answers'
        result = await http(base, 'POST', route, environment['user']['token'], payload, proof, consume_ack=not lose_ack)
        if lose_ack:
            row = await (await connection.execute('SELECT id FROM requests WHERE operation_key=%s', (operation,))).fetchone()
            request_id = str(row['id'])
        else:
            request_id = result['id']
        requests.append(request_id)
        return request_id, route, payload, proof

    async def applied(base, revision):
        current = await http(base, 'GET', '/api/settings', environment['super_admin']['token'])
        return current if current['revision'] == current['applied_revision'] == revision else None

    async def snapshot(base, request_id):
        row = await (await connection.execute('SELECT conversation_id FROM requests WHERE id=%s', (request_id,))).fetchone()
        result = await http(base, 'GET', f"/api/conversations/{row['conversation_id']}", environment['user']['token'])
        return next(request for request in result['requests'] if request['id'] == request_id)

    try:
        supervisor, native_log = launch('supervisor', [sys.executable, str(bootstrap)])

        async def healthy():
            assert supervisor.poll() is None, native_log.read_text(errors='replace')
            row = await (await connection.execute('SELECT s.epoch,l.healthy_until>clock_timestamp() AS healthy FROM service_state s JOIN coordinator_lease l USING(id,epoch)')).fetchone()
            return row if row['healthy'] and row['epoch'] > 1 else None

        service = await eventually(healthy)
        spawn = next(value for value in traces(native_log) if value['event'] == 'native_spawn')
        native_pid = spawn['pid']
        first_api, first = await api('api-1')
        _, second = await api('api-2')
        initial_settings = await http(first, 'GET', '/api/settings', environment['super_admin']['token'])
        assert initial_settings['revision'] == 0
        assert initial_settings['values']['max_active'] == 12 and initial_settings['values']['step_width'] == 3
        first_request, route, payload, proof = await submit(first, lose_ack=True)
        replay = await http(second, 'POST', route, environment['user']['token'], payload, proof)
        assert replay['id'] == first_request
        for index in range(1, 13):
            await submit(second if index % 2 else first)
        original = set(requests[:12])
        waiting = requests[12]

        async def at_capacity():
            active = live_contexts(traces(native_log))
            row = await (await connection.execute('SELECT state,passport FROM requests WHERE id=%s', (waiting,))).fetchone()
            return active if set(active) == original and row['state'] == 'queued' else None

        pointers = await eventually(at_capacity)
        assert len(set(pointers.values())) == 12 and all(pointers.values())
        rss_bytes = int(Path(f'/proc/{native_pid}/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')

        async def fair_round(revision, width, expected, after):
            events = traces(native_log)
            steps = [value for value in events[after:] if value['event'] == 'native_step' and value['revision'] == revision]
            assert all(value['step_width'] == width and len(value['promoted']) <= width for value in steps)
            for start in range(len(steps)):
                batch = steps[start:start + (len(expected) + width - 1) // width]
                promoted = [item['request'] for value in batch for item in value['promoted']]
                if len(promoted) == len(expected) and set(promoted) == expected:
                    assert len(set(promoted)) == len(promoted)
                    return [value['step'] for value in batch]
            return None

        baseline_boundary = len(traces(native_log))
        first_round = await eventually(lambda: fair_round(0, 3, original, baseline_boundary))
        allocations = [value for value in traces(native_log) if value['event'] == 'native_allocate']
        assert len(allocations) == 12 and all(1400 <= value['prompt_tokens'] <= 2400 for value in allocations)
        for request_id in original | {waiting}:
            row = await (await connection.execute('SELECT passport FROM requests WHERE id=%s', (request_id,))).fetchone()
            assert [value['id'] for value in row['passport']['passed']] == [str(chunk)]
            assert row['passport']['passed'][0]['revision_id'] == str(revision)

        shrink_boundary = len(traces(native_log))
        saved = await http(second, 'PATCH', '/api/settings', environment['super_admin']['token'], {'max_active': 6, 'step_width': 2})
        assert saved['revision'] == 1
        await eventually(lambda: applied(first, 1))
        shrink_round = await eventually(lambda: fair_round(1, 2, original, shrink_boundary))
        assert live_contexts(traces(native_log)) == pointers
        assert (await snapshot(second, waiting))['state'] == 'queued'

        # Six actual close ACKs leave six contexts: the queued request must still wait.
        for index, request_id in enumerate(requests[:6]):
            await http(first if index % 2 else second, 'POST', f'/api/answers/{request_id}/stop', environment['user']['token'])

        async def six_survivors():
            active = live_contexts(traces(native_log))
            return active if set(active) == original - set(requests[:6]) else None

        await eventually(six_survivors)
        assert (await snapshot(first, waiting))['state'] == 'queued'
        await http(second, 'POST', f'/api/answers/{requests[6]}/stop', environment['user']['token'])
        retained = original - set(requests[:7])

        async def queued_admitted():
            active = live_contexts(traces(native_log))
            return active if set(active) == retained | {waiting} else None

        await eventually(queued_admitted)
        events = traces(native_log)
        admission_index = next(index for index, value in enumerate(events) if value['event'] == 'native_allocate' and value['request'] == waiting)
        assert live_contexts(events[:admission_index]) == {key: pointers[key] for key in retained}
        admission = events[admission_index]
        assert admission['physical_active'] == admission['max_active'] == 6 and admission['revision'] == 1
        assert {value['request'] for value in events[:admission_index] if value['event'] == 'native_release'} == set(requests[:7])

        saved = await http(first, 'PATCH', '/api/settings', environment['super_admin']['token'], {'max_active': 12, 'step_width': 4})
        assert saved['revision'] == 2
        await eventually(lambda: applied(second, 2))
        for index in range(6):
            await submit(second if index % 2 else first)
        expanded = retained | {waiting} | set(requests[13:])

        async def expanded_capacity():
            active = live_contexts(traces(native_log))
            return active if set(active) == expanded else None

        expanded_pointers = await eventually(expanded_capacity)
        assert len(set(expanded_pointers.values())) == 12
        assert {key: expanded_pointers[key] for key in retained} == {key: pointers[key] for key in retained}
        expanded_boundary = len(traces(native_log))
        expanded_round = await eventually(lambda: fair_round(2, 4, expanded, expanded_boundary))

        restart_boundary = len(traces(native_log))
        await stop_process(first_api)
        assert (await snapshot(second, waiting))['state'] == 'generating'
        _, restarted = await api('api-1-restarted')
        persisted = await http(restarted, 'GET', '/api/settings', environment['super_admin']['token'])
        assert persisted['revision'] == persisted['applied_revision'] == 2
        assert persisted['values']['max_active'] == 12 and persisted['values']['step_width'] == 4
        restart_round = await eventually(lambda: fair_round(2, 4, expanded, restart_boundary))
        assert live_contexts(traces(native_log)) == expanded_pointers
        assert (await healthy())['epoch'] == service['epoch']
        assert len([value for value in traces(native_log) if value['event'] == 'native_spawn']) == 1

        for index, request_id in enumerate(requests):
            await http(restarted if index % 2 else second, 'POST', f'/api/answers/{request_id}/stop', environment['user']['token'])

        async def released():
            events = traces(native_log)
            released_ids = {value['request'] for value in events if value['event'] == 'native_release'}
            return bool(not live_contexts(events) and released_ids == set(requests))

        await eventually(released)
        final_events = traces(native_log)
        assert len([event for event in final_events if event['event'] == 'native_allocate']) == 19
        assert len([event for event in final_events if event['event'] == 'native_release']) == 19
        for event in final_events:
            if event['event'] == 'native_step':
                assert event['epoch'] == service['epoch']
                assert event['step_width'] == {0: 3, 1: 2, 2: 4}[event['revision']]
                assert len(event['promoted']) <= event['step_width']
                assert len({item['request'] for item in event['promoted']}) == len(event['promoted'])
        assert (await (await connection.execute('SELECT count(*) AS n FROM requests')).fetchone())['n'] == 19
        print(json.dumps({'proof': 'two_actual_api_processes', 'epoch': service['epoch'],
                          'native_pid': native_pid, 'source_similarity': similarity,
                          'default_active': 12, 'waiting': waiting, 'rss_at_twelve_bytes': rss_bytes,
                          'rounds': [first_round, shrink_round, expanded_round, restart_round],
                          'all_native_release_acks': 19, 'logs': str(log_directory)}), flush=True)
    finally:
        for process in reversed(processes):
            await stop_process(process)
        for stream in streams:
            stream.close()
        if native_pid is not None:
            assert not Path(f'/proc/{native_pid}').exists(), 'Supervisor stop must reap its native child'
