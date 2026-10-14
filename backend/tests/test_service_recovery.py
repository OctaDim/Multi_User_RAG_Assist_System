import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from time import monotonic

import pytest

from test_scheduler import submit


async def wait_for(predicate, timeout=30):
    until = monotonic() + timeout
    while monotonic() < until:
        value = await predicate()
        if value:
            return value
        await asyncio.sleep(0.05)
    raise AssertionError('Expected process state was not reached')


@pytest.mark.parametrize('mode', ['SHARE', 'UPDATE'])
async def test_application_service_lock_does_not_cancel_healthy_supervisor(environment, connection, tmp_path, mode):
    path = tmp_path / 'healthy-supervisor.log'
    env = dict(os.environ, RAG_DATABASE_URL=environment['dsn'])
    native_pid = None
    with path.open('xb') as log:
        process = subprocess.Popen([sys.executable, '-m', 'app.generation'], cwd='backend',
                                   env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            async def ready():
                assert process.poll() is None, path.read_text()
                row = await (await connection.execute('SELECT s.epoch,l.healthy_until>clock_timestamp() AS healthy FROM service_state s JOIN coordinator_lease l USING(id,epoch)')).fetchone()
                return row if row['epoch'] > 1 and row['healthy'] else None

            service = await wait_for(ready)
            native_pid = next(json.loads(line)['pid'] for line in path.read_text().splitlines()
                              if line.startswith('{"event": "native_spawn"'))
            async with connection.transaction():
                await connection.execute(f'SELECT id FROM service_state WHERE id=1 FOR {mode}')
                await asyncio.sleep(1)
                assert Path(f'/proc/{native_pid}').exists(), 'An application fence is not loss of coordinator ownership'
            assert (await ready())['epoch'] == service['epoch']
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    await asyncio.to_thread(process.wait, 15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait, 10)
            if native_pid is not None:
                assert not Path(f'/proc/{native_pid}').exists()


async def test_real_supervisor_reaps_native_process_before_replacement(environment, connection, tmp_path):
    env = dict(os.environ, RAG_DATABASE_URL=environment['dsn'])
    processes = []
    logs = []
    decode = tmp_path / 'inside-native-decode'
    hook = tmp_path / 'native-hook.py'
    hook.write_text(f'''from pathlib import Path
import os,time
from app.llama_runtime import LlamaContext,native
original=LlamaContext.__init__
marker=Path({str(decode)!r})
def initialize(self,*args,**kwargs):
    original(self,*args,**kwargs)
    @native.ggml_abort_callback
    def abort(_):
        if self.output_tokens and not self._decoder.getstate()[0] and not marker.exists():
            marker.write_text(str(os.getpid()))
            while True: time.sleep(0.01)
        return self._cancelled.is_set()
    self._test_callback=abort
    native.llama_set_abort_callback(self.context,abort,None)
LlamaContext.__init__=initialize
from app.generation import main
main()
''')
    launcher = tmp_path / 'supervisor-launcher.py'
    launcher.write_text(f'''from app import generation
original=generation.subprocess.Popen
def spawn(args,**kwargs):
    if '--worker' in args:
        args=[args[0],{str(hook)!r},*args[3:]]
    return original(args,**kwargs)
generation.subprocess.Popen=spawn
generation.main()
''')

    def launch(name):
        log = tmp_path / name
        out = log.open('wb')
        logs.append(out)
        process = subprocess.Popen([sys.executable, str(launcher)], cwd='backend',
                                   env=env, stdout=out, stderr=subprocess.STDOUT)
        processes.append(process)
        return process, log

    async def healthy_after(epoch):
        row = await (await connection.execute('SELECT s.epoch,l.healthy_until>clock_timestamp() AS healthy FROM service_state s JOIN coordinator_lease l USING(id,epoch)')).fetchone()
        return row if row['epoch'] > epoch and row['healthy'] else None

    def owner(log):
        return next(json.loads(line) for line in log.read_text().splitlines() if line.startswith('{"event": "native_spawn"'))

    try:
        first, first_log = launch('first-supervisor.log')
        service = await wait_for(lambda: healthy_after(1))
        predecessor = owner(first_log)
        competing, competing_log = launch('competing-supervisor.log')
        assert await asyncio.to_thread(competing.wait, 15) != 0
        assert 'Generation supervisor already owns this service' in competing_log.read_text()
        assert 'native_spawn' not in competing_log.read_text()
        request = await submit(connection, environment)

        async def prefix():
            row = await (await connection.execute('SELECT * FROM requests WHERE id=%s', (request['id'],))).fetchone()
            return row if row['answer_text'] and row['state'] == 'generating' else None

        partial = await wait_for(prefix)
        async def inside_decode():
            return decode.exists()
        await wait_for(inside_decode)
        assert int(decode.read_text()) == predecessor['pid']
        assert Path(f"/proc/{predecessor['pid']}").exists()
        # Keep the supervisor from reaping while a real successor tries to acquire
        # the now-free DB ownership. The inherited native host fence must win.
        first.send_signal(signal.SIGSTOP)
        assert (await (await connection.execute('SELECT pg_terminate_backend(%s) AS terminated', (predecessor['keeper_pid'],))).fetchone())['terminated']
        blocked, blocked_log = launch('unreaped-successor.log')
        assert await asyncio.to_thread(blocked.wait, 15) != 0
        assert 'native_spawn' not in blocked_log.read_text(), 'Successor loaded before physical predecessor termination'
        assert Path(f"/proc/{predecessor['pid']}").exists()
        first.send_signal(signal.SIGCONT)
        await asyncio.to_thread(first.wait, 15)
        assert not Path(f"/proc/{predecessor['pid']}").exists(), 'Confirmed reap must precede replacement load'
        second, second_log = launch('second-supervisor.log')
        await wait_for(lambda: healthy_after(service['epoch']))
        replacement = owner(second_log)
        assert replacement['pid'] != predecessor['pid']
        row = await (await connection.execute('SELECT * FROM requests WHERE id=%s', (request['id'],))).fetchone()
        assert row['state'] == 'interrupted' and row['reason'] == 'execution_lost'
        assert row['answer_text'].startswith(partial['answer_text'])
        message = await (await connection.execute("SELECT * FROM messages WHERE request_id=%s AND role='assistant'", (request['id'],))).fetchone()
        assert message['text'] == row['answer_text'] and message['excluded']
        state_events = await (await connection.execute(
            "SELECT payload->>'state' AS state FROM events WHERE request_id=%s AND kind='state' ORDER BY id", (request['id'],),
        )).fetchall()
        assert [event['state'] for event in state_events] == ['searching', 'generating']
        print({'proof': 'supervisor_physical_reap', 'predecessor': predecessor, 'replacement': replacement,
               'saved_prefix_chars': len(row['answer_text']), 'inside_real_native_decode': True,
               'native_logs': str(tmp_path)}, flush=True)
    finally:
        for process in processes:
            if process.poll() is None:
                process.send_signal(signal.SIGCONT)
                process.send_signal(signal.SIGTERM)
                try:
                    await asyncio.to_thread(process.wait, 15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait, 10)
        for out in logs:
            out.close()


async def test_live_predecessor_record_blocks_unconfirmed_replacement(environment,connection,tmp_path):
    from app.generation import Supervisor
    predecessor=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
    supervisor=Supervisor(environment['dsn'])
    runtime=(await (await connection.execute('SELECT runtime_id FROM service_state WHERE id=1')).fetchone())['runtime_id']
    supervisor.acquire_fence(runtime)
    supervisor.child=predecessor
    supervisor.record_child()
    os.close(supervisor.fence);supervisor.fence=None
    path=tmp_path/'unconfirmed-record.log'
    try:
        with path.open('xb') as log:
            successor=subprocess.Popen([sys.executable,'-m','app.generation'],cwd='backend',
                env=dict(os.environ,RAG_DATABASE_URL=environment['dsn']),stdout=log,stderr=subprocess.STDOUT)
            try:
                assert await asyncio.to_thread(successor.wait,15)!=0
            finally:
                if successor.poll() is None:successor.kill();await asyncio.to_thread(successor.wait,10)
        assert predecessor.poll() is None
        assert 'Predecessor reap is unconfirmed; replacement blocked' in path.read_text()
        assert 'native_spawn' not in path.read_text()
        assert (await (await connection.execute('SELECT epoch FROM service_state WHERE id=1')).fetchone())['epoch']==1
    finally:
        predecessor.terminate();await asyncio.to_thread(predecessor.wait,10)


async def test_real_coordinator_recovery_reconciles_all_pre_token_states_and_keeps_completed(environment,connection,tmp_path):
    from uuid import uuid4
    from app import answers
    requests=[]
    for state in ('accepted','searching','queued','generating','completed'):
        room=uuid4()
        await connection.execute('INSERT INTO conversations(id,owner_id) VALUES (%s,%s)',(room,environment['user']['id']))
        request=await answers.admit(connection,environment['user']['token'],room,uuid4(),'Budget?',
            [environment['document']],environment['tab'],environment['proof'])
        await connection.execute('UPDATE requests SET state=%s WHERE id=%s',(state,request['id']))
        if state=='completed':
            await connection.execute("UPDATE requests SET answer_text='SAVED COMPLETED' WHERE id=%s",(request['id'],))
            await connection.execute("INSERT INTO messages(request_id,conversation_id,role,text) VALUES (%s,%s,'assistant','SAVED COMPLETED')",(request['id'],room))
        requests.append((state,request))
    path=tmp_path/'state-recovery.log'
    with path.open('xb') as log:
        process=subprocess.Popen([sys.executable,'-m','app.generation'],cwd='backend',env=dict(os.environ,
            RAG_DATABASE_URL=environment['dsn']),stdout=log,stderr=subprocess.STDOUT)
        try:
            async def healthy():
                assert process.poll() is None,path.read_text()
                row=await (await connection.execute('SELECT epoch,healthy_until>clock_timestamp() AS healthy FROM coordinator_lease WHERE id=1')).fetchone()
                return row if row['epoch']>1 and row['healthy'] else None
            await wait_for(healthy)
            for original,request in requests:
                row=await (await connection.execute('SELECT * FROM requests WHERE id=%s',(request['id'],))).fetchone()
                messages=await (await connection.execute("SELECT * FROM messages WHERE request_id=%s AND role='assistant'",(request['id'],))).fetchall()
                if original=='completed':
                    assert row['state']=='completed' and row['answer_text']=='SAVED COMPLETED'
                    assert messages[0]['text']=='SAVED COMPLETED' and not messages[0]['excluded']
                else:
                    assert row['state']=='interrupted' and row['reason']=='execution_lost' and not messages
                assert not (await (await connection.execute('SELECT started FROM graph_bindings WHERE request_id=%s',(request['id'],))).fetchone())['started']
        finally:
            process.terminate()
            try:await asyncio.to_thread(process.wait,15)
            except subprocess.TimeoutExpired:process.kill();await asyncio.to_thread(process.wait,10)
