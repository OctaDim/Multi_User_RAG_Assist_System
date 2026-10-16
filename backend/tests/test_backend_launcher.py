import asyncio
import json
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import sys
import time
from urllib.request import urlopen

import pytest


BACKEND = Path(__file__).parents[1]


def wait_file(path, process, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.read_text().strip():
            return path.read_text()
        if process.poll() is not None:
            raise AssertionError(process.communicate()[1])
        time.sleep(.02)
    raise AssertionError(f'No process readiness record: {path}')


def running(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z'
    except FileNotFoundError:
        return False


@pytest.mark.parametrize('stop_signal', [signal.SIGINT, signal.SIGTERM])
def test_signals_stop_descendants_even_when_their_leader_has_exited(tmp_path, stop_signal):
    child = tmp_path / 'child.py'
    child.write_text('''import os,signal,subprocess,sys,time
from pathlib import Path
grandchild=subprocess.Popen([sys.executable,'-c',
 "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(120)"])
Path(sys.argv[1]).write_text(str(os.getpid())+','+str(grandchild.pid))
while True:time.sleep(1)
''')
    pids = tmp_path / 'pids'
    harness = '''import os,sys,threading
from app.launcher import run_processes, stop_signals
stop=threading.Event()
with stop_signals(stop):
 code=run_processes([('owned',[sys.executable,sys.argv[1],sys.argv[2]])],
   cwd=os.getcwd(),env=os.environ.copy(),settings={'poll_seconds':.02,
   'shutdown_timeout_seconds':.15,'kill_timeout_seconds':2},stopping=stop)
raise SystemExit(code)
'''
    process = subprocess.Popen([sys.executable, '-c', harness, str(child), str(pids)],
                               cwd=BACKEND, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    recorded = []
    try:
        recorded = [int(value) for value in wait_file(pids, process).split(',')]
        process.send_signal(stop_signal)
        assert process.wait(5) == 0, process.communicate()
        assert all(not running(pid) for pid in recorded)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(5)
        for pid in recorded:
            if running(pid):
                os.kill(pid, signal.SIGKILL)


@pytest.mark.parametrize('exit_code', [0, 7])
def test_unexpected_child_exit_fails_launch_and_stops_sibling(tmp_path, exit_code):
    pid_file = tmp_path / 'pid'
    script = '''import os,sys,threading
from app.launcher import run_processes, stop_signals
stop=threading.Event()
sibling="import os,sys,time;from pathlib import Path;Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(120)"
failure="import sys,time;time.sleep(.25);sys.exit(int(sys.argv[1]))"
with stop_signals(stop):
 code=run_processes([('sibling',[sys.executable,'-c',sibling,sys.argv[1]]),
 ('failure',[sys.executable,'-c',failure,sys.argv[2]])],cwd=os.getcwd(),env=os.environ.copy(),
 settings={'poll_seconds':.02,'shutdown_timeout_seconds':.2,'kill_timeout_seconds':2},stopping=stop)
raise SystemExit(code)
'''
    result = subprocess.run([sys.executable, '-c', script, str(pid_file), str(exit_code)],
                            cwd=BACKEND, capture_output=True, text=True, timeout=8)
    assert result.returncode != 0
    assert 'failure exited unexpectedly' in result.stderr
    assert not running(int(pid_file.read_text()))


@pytest.mark.asyncio
async def test_database_readiness_uses_existing_database_owner(postgres):
    from app.launcher import wait_for_database
    import threading
    assert await wait_for_database(postgres, timeout=3, retry=.02, connect_timeout=1,
                                   stopping=threading.Event())


@pytest.mark.asyncio
async def test_database_wait_is_bounded_for_silent_peer():
    import asyncio
    import threading
    from app.launcher import wait_for_database
    connections = []

    async def silent(reader, writer):
        connections.append(writer)
        await reader.read()

    server = await asyncio.start_server(silent, '127.0.0.1', 0)
    try:
        port = server.sockets[0].getsockname()[1]
        started = time.monotonic()
        with pytest.raises(RuntimeError, match='PostgreSQL readiness timed out'):
            await wait_for_database(f'host=127.0.0.1 port={port} user=owned dbname=owned sslmode=disable',
                                    timeout=.3, retry=.02, connect_timeout=1, stopping=threading.Event())
        assert time.monotonic() - started < 2
    finally:
        server.close()
        for writer in connections:
            writer.close()
            await writer.wait_closed()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_database_deadline_bounds_a_peer_that_stalls_after_authentication():
    import threading
    from app.launcher import wait_for_database
    connections = []
    authenticated_query = asyncio.Event()

    def packet(kind, payload):
        return kind + struct.pack('!I', len(payload) + 4) + payload

    async def peer(reader, writer):
        connections.append(writer)
        try:
            size = struct.unpack('!I', await reader.readexactly(4))[0]
            startup = await reader.readexactly(size - 4)
            if startup[:4] != struct.pack('!I', 196608):
                return  # libpq cancellation request, not a normal startup.
            writer.write(packet(b'R', struct.pack('!I', 0)) +
                         packet(b'S', b'server_version\x0016.0\x00') +
                         packet(b'S', b'client_encoding\x00UTF8\x00') +
                         packet(b'K', struct.pack('!II', 123, 456)) + packet(b'Z', b'I'))
            await writer.drain()
            if await reader.read(1):
                authenticated_query.set()
            await reader.read()  # Deliberately never reply to the first query.
        except (asyncio.IncompleteReadError, ConnectionError):
            pass

    server = await asyncio.start_server(peer, '127.0.0.1', 0)
    try:
        port = server.sockets[0].getsockname()[1]
        started = time.monotonic()
        with pytest.raises(RuntimeError, match='PostgreSQL readiness timed out'):
            await wait_for_database(f'host=127.0.0.1 port={port} user=owned dbname=owned sslmode=disable',
                                    timeout=1.5, retry=.02, connect_timeout=2, stopping=threading.Event())
        assert authenticated_query.is_set(), 'The peer must stall after authentication, not before it'
        assert time.monotonic() - started < 4
    finally:
        server.close()
        for writer in connections:
            writer.close()
        for writer in connections:
            await writer.wait_closed()
        await server.wait_closed()


def test_backend_main_config_error_from_foreign_directory_does_not_echo_secret(tmp_path):
    local = tmp_path / 'invalid.toml'
    local.write_text('[database]\ndsn=""\n[smtp]\npassword="secret-must-not-leak"\n')
    result = subprocess.run([sys.executable, str(BACKEND / 'main.py'), '--config', str(local)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=8)
    assert result.returncode != 0
    assert 'database.dsn' in result.stderr
    assert 'secret-must-not-leak' not in result.stderr


@pytest.mark.asyncio
@pytest.mark.parametrize('config_source', ['cli', 'environment'])
@pytest.mark.parametrize('stop_signal', [signal.SIGINT, signal.SIGTERM])
async def test_real_backend_main_starts_models_api_and_stops_whole_tree(environment, tmp_path, config_source, stop_signal):
    from app.auth import lock_service
    from app.db import Database

    resources = {key: os.environ.get(variable) for key, variable in
                 [('generation', 'RAG_MODEL_PATH'), ('embedding', 'RAG_E5_DIR'), ('ocr', 'RAG_OCR_DIR')]}
    if not all(resources.values()):
        pytest.skip('Real model resources are required for the complete backend smoke')
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    local = tmp_path / 'service.toml'
    local.write_text('[database]\ndsn = ' + json.dumps(environment['dsn']) +
                     f'\n[api]\nport = {port}\n[models]\n' +
                     '\n'.join(f'{key} = {json.dumps(value)}' for key, value in resources.items()))
    log_path = tmp_path / 'backend.log'
    database = Database(environment['dsn'])
    owned = []
    # Exercise the system-Python command requested by the user, including
    # virtualenv bootstrap, foreign cwd and propagation of --config to children.
    command = ['python3', str(BACKEND / 'main.py')]
    child_env = os.environ.copy()
    if config_source == 'cli':
        command.extend(['--config', str(local)])
    else:
        child_env['RAG_SERVICE_CONFIG'] = local.name
        with local.open('a') as stream:
            stream.write('\n[launcher]\npython = "../backend/.venv/bin/python"\n')
    with log_path.open('w') as output:
        process = subprocess.Popen(command, env=child_env, cwd=tmp_path, stdout=output, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 90
            while True:
                assert process.poll() is None, log_path.read_text()
                async with database.session() as session, session.begin():
                    state = await lock_service(session)
                try:
                    with urlopen(f'http://127.0.0.1:{port}/openapi.json', timeout=.25) as response:
                        api_ready = response.status == 200
                except OSError:
                    api_ready = False
                if state['healthy'] and api_ready and 'native_spawn' in log_path.read_text():
                    break
                assert time.monotonic() < deadline, log_path.read_text()
                await asyncio.sleep(.1)
            for line in log_path.read_text().splitlines():
                if line.startswith('Backend started '):
                    owned.append(int(line.rsplit('pid=', 1)[1].rstrip(')')))
                elif line.startswith('{'):
                    event = json.loads(line)
                    if event.get('event') == 'native_spawn':
                        owned.append(event['pid'])
            assert len(owned) == 4, log_path.read_text()
            assert all(running(pid) for pid in owned)
            process.send_signal(stop_signal)
            await asyncio.to_thread(process.wait, 15)
            assert process.returncode == 0, log_path.read_text()
            assert all(not running(pid) for pid in owned)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    await asyncio.to_thread(process.wait, 15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait, 5)
            await database.dispose()
