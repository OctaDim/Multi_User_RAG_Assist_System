import asyncio
from collections import deque
import threading
from uuid import uuid4

import pytest

from app import answers, settings
from app.generation import Coordinator
from test_rag_context import ContractEmbedder


class TokenContext:
    def __init__(self, runtime, request_id):
        self.runtime, self.request_id = runtime, request_id
        self.cancelled = False
        self.close_gate = threading.Event()
        self.close_gate.set()
        self.pieces = deque(['первый ', 'второй ', None])

    def cancel(self):
        self.cancelled = True

    def advance(self):
        self.runtime.trace.append(self.request_id)
        if self.runtime.advance_hook:
            self.runtime.advance_hook(self)
        piece = self.pieces.popleft()
        if isinstance(piece, Exception):
            raise piece
        return {'phase': 'token', 'text': piece or '', 'done': piece is None,
                'reason': 'eos' if piece is None else None}

    def close(self):
        self.close_gate.wait(10)
        self.runtime.live.discard(self.request_id)


class TokenRuntime:
    def __init__(self):
        self.live, self.trace, self.contexts = set(), [], {}
        self.advance_hook = None
        self.allocate_hook = None

    def tokenize(self, text):
        return list(text.encode())

    def allocate(self, request_id, tokens):
        assert request_id not in self.live
        self.live.add(request_id)
        context = TokenContext(self, request_id)
        self.contexts[request_id] = context
        if self.allocate_hook:
            self.allocate_hook(context)
        return context


async def submit(connection, environment):
    conversation = uuid4()
    await connection.execute('INSERT INTO conversations(id,owner_id) VALUES (%s,%s)',
                             (conversation, environment['user']['id']))
    return await answers.admit(connection, environment['user']['token'], conversation,
                               uuid4(), 'What is the budget?', [environment['document']],
                               environment['tab'], environment['proof'])


async def settle(coordinator, turns=10):
    for _ in range(turns):
        await coordinator.tick()
        await asyncio.sleep(0.01)


async def test_global_round_robin_and_hot_settings_keep_native_reservations(environment, connection, rag_pool):
    requests = [await submit(connection, environment) for _ in range(13)]
    runtime = TokenRuntime()
    coordinator = Coordinator(rag_pool, 1, runtime, ContractEmbedder())
    try:
        for _ in requests:
            await coordinator.prepare_next()
        await coordinator.admit_ready()
        assert len(runtime.live) == 12 and requests[-1]['id'] not in runtime.live
        for context in runtime.contexts.values():
            context.pieces = deque(['token '] * 8 + [None])
        for _ in range(4):
            await coordinator.step()
        assert len(runtime.trace) == 12 and len(set(runtime.trace)) == 12
        runtime.trace.clear()
        await settings.write(connection, environment['super_admin']['token'], {'max_active': 6, 'step_width': 2})
        await coordinator.step()
        assert len(runtime.trace) == 2 and len(runtime.live) == 12
        for request in requests[:7]:
            await answers.stop(connection, environment['user']['token'], request['id'])
        await settle(coordinator, 2)
        assert requests[-1]['id'] in runtime.live
        assert len(runtime.live) <= 6
        await settings.write(connection, environment['super_admin']['token'], {'max_active': 12, 'step_width': 4})
        runtime.trace.clear()
        await coordinator.step()
        assert len(runtime.trace) == 4 and len(set(runtime.trace)) == 4
        current = await settings.read(connection, environment['super_admin']['token'])
        assert current['revision'] == current['applied_revision'] == 2
    finally:
        await coordinator.close()


async def test_saved_shrink_during_allocation_applies_before_next_admission(environment, connection, rag_pool):
    await settings.write(connection, environment['super_admin']['token'], {'max_active': 2})
    runtime = TokenRuntime()
    coordinator = Coordinator(rag_pool, 1, runtime, ContractEmbedder())
    first, second = await submit(connection, environment), await submit(connection, environment)
    entered, release = threading.Event(), threading.Event()

    def allocation(context):
        entered.set()
        assert release.wait(10)

    runtime.allocate_hook = allocation
    try:
        await coordinator.prepare_next()
        await coordinator.prepare_next()
        admission = asyncio.create_task(coordinator.admit_ready())
        assert await asyncio.to_thread(entered.wait, 10)
        await settings.write(connection, environment['super_admin']['token'], {'max_active': 1})
        release.set()
        await admission
        assert runtime.live == {first['id']} and second['id'] not in runtime.contexts
    finally:
        release.set()
        await coordinator.close()


async def test_stop_wins_dequeue_and_late_computed_token_is_not_committed(environment, connection, rag_pool):
    runtime = TokenRuntime()
    coordinator = Coordinator(rag_pool, 1, runtime, ContractEmbedder())
    queued = await submit(connection, environment)
    try:
        await coordinator.prepare_next()
        await answers.stop(connection, environment['user']['token'], queued['id'])
        await coordinator.admit_ready()
        assert not runtime.live
        request = await submit(connection, environment)
        await coordinator.prepare_next()
        await coordinator.admit_ready()
        entered, release = threading.Event(), threading.Event()

        def computed(context):
            entered.set()
            assert release.wait(10)

        runtime.advance_hook = computed
        step = asyncio.create_task(coordinator.step())
        assert await asyncio.to_thread(entered.wait, 10)
        await answers.stop(connection, environment['user']['token'], request['id'])
        release.set()
        await step
        assert not await (await connection.execute("SELECT 1 FROM messages WHERE request_id=%s AND role='assistant'", (request['id'],))).fetchone()
        assert not await (await connection.execute("SELECT 1 FROM events WHERE request_id=%s AND kind='output'", (request['id'],))).fetchone()
    finally:
        await coordinator.close()


@pytest.mark.parametrize('partial', [False, True])
async def test_native_error_preserves_only_committed_prefix_without_retry(environment, connection, rag_pool, partial):
    runtime = TokenRuntime()
    coordinator = Coordinator(rag_pool, 1, runtime, ContractEmbedder())
    request = await submit(connection, environment)
    try:
        await coordinator.prepare_next()
        await coordinator.admit_ready()
        context = runtime.contexts[request['id']]
        if partial:
            await coordinator.step()
        context.pieces = deque([RuntimeError('native failure')])
        await coordinator.step()
        row = await (await connection.execute('SELECT * FROM requests WHERE id=%s', (request['id'],))).fetchone()
        assert row['state'] == 'failed' and row['reason'] == 'generation_error'
        messages = await (await connection.execute("SELECT * FROM messages WHERE request_id=%s AND role='assistant'", (request['id'],))).fetchall()
        assert bool(messages) == partial
        if partial:
            assert messages[0]['text'] == 'первый ' and messages[0]['excluded']
        await settle(coordinator, 3)
        assert not runtime.live
        assert len(runtime.trace) == (2 if partial else 1)
        await submit(connection, environment)
    finally:
        await coordinator.close()


async def test_logical_stop_does_not_release_physical_slot_until_ack(environment, connection, rag_pool):
    await settings.write(connection, environment['super_admin']['token'], {'max_active': 1})
    runtime = TokenRuntime()
    coordinator = Coordinator(rag_pool, 1, runtime, ContractEmbedder())
    first, second = await submit(connection, environment), await submit(connection, environment)
    try:
        await coordinator.prepare_next()
        await coordinator.prepare_next()
        await coordinator.admit_ready()
        context = runtime.contexts[first['id']]
        context.close_gate.clear()
        await answers.stop(connection, environment['user']['token'], first['id'])
        await coordinator.tick()
        assert runtime.live == {first['id']} and second['id'] not in runtime.contexts
        context.close_gate.set()
        await settle(coordinator, 2)
        assert first['id'] not in runtime.live and second['id'] in runtime.contexts
    finally:
        for context in runtime.contexts.values():
            context.close_gate.set()
        await coordinator.close()


async def test_failed_native_allocation_releases_reservation_without_empty_answer(environment, connection, rag_pool):
    runtime = TokenRuntime()
    coordinator = Coordinator(rag_pool, 1, runtime, ContractEmbedder())
    request = await submit(connection, environment)

    def failed_allocation(*args):
        raise RuntimeError('Native context allocation failed')

    runtime.allocate = failed_allocation
    try:
        await coordinator.prepare_next()
        await coordinator.admit_ready()
        row = await (await connection.execute('SELECT * FROM requests WHERE id=%s', (request['id'],))).fetchone()
        assert row['state'] == 'failed' and row['reason'] == 'generation_error'
        assert not coordinator.active and not runtime.live
        assert not await (await connection.execute("SELECT 1 FROM messages WHERE request_id=%s AND role='assistant'", (request['id'],))).fetchone()
        await answers.admit(connection, environment['user']['token'], request['conversation_id'], uuid4(),
                            'A new explicit question', [environment['document']], environment['tab'], environment['proof'])
    finally:
        await coordinator.close()


async def test_search_state_is_published_before_graph_work(environment, connection, rag_pool):
    import psycopg
    from psycopg.rows import dict_row

    request = await submit(connection, environment)
    observed = []

    class InspectSearch(ContractEmbedder):
        def encode(self, texts, *, query=False):
            with psycopg.connect(environment['dsn'], row_factory=dict_row) as independent:
                row = independent.execute('SELECT state,version FROM requests WHERE id=%s', (request['id'],)).fetchone()
                events = independent.execute('SELECT kind,payload FROM events WHERE request_id=%s ORDER BY id', (request['id'],)).fetchall()
                observed.append((row, events))
            return super().encode(texts, query=query)

    coordinator = Coordinator(rag_pool, 1, TokenRuntime(), InspectSearch())
    try:
        await coordinator.prepare_next()
        assert len(observed) == 1
        row, events = observed[0]
        assert row == {'state': 'searching', 'version': request['version'] + 1}
        assert [event['kind'] for event in events] == ['accepted', 'state']
        assert events[-1]['payload'] == {'state': 'searching', 'version': row['version']}
        final = await (await connection.execute('SELECT state,version FROM requests WHERE id=%s', (request['id'],))).fetchone()
        assert final == {'state': 'queued', 'version': row['version'] + 1}
    finally:
        await coordinator.close()
