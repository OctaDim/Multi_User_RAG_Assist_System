"""Own the backend process tree without loading the inference stack."""
import asyncio
from contextlib import contextmanager
import ctypes
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

from psycopg.conninfo import make_conninfo
from sqlalchemy import literal, select

from app.configuration import ConfigurationError, load_settings
from app.db import Database
from app.resources import resource_path


@contextmanager
def stop_signals(stopping):
    previous = {number: signal.signal(number, lambda *_: stopping.set())
                for number in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


async def wait_for_database(dsn, *, timeout, retry, connect_timeout, stopping):
    # A driver may spend seconds cancelling an authenticated, stalled query.
    # Put the existing Database owner in a disposable process so its cleanup
    # cannot overrun the operator's readiness deadline.
    env = os.environ.copy()
    env['RAG_DATABASE_URL'] = make_conninfo(dsn, connect_timeout=connect_timeout)
    deadline = time.monotonic() + timeout
    while not stopping.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError('PostgreSQL readiness timed out; check database.dsn and PostgreSQL availability')
        process = await asyncio.create_subprocess_exec(
            sys.executable, '-m', 'app.launcher', '--database-probe',
            cwd=resource_path('config').parent, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        attempt_deadline = min(deadline, time.monotonic() + connect_timeout)
        try:
            while process.returncode is None and not stopping.is_set() and time.monotonic() < attempt_deadline:
                await asyncio.sleep(min(retry, max(0, attempt_deadline - time.monotonic())))
            if process.returncode == 0:
                return True
        finally:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await process.wait()
        await asyncio.sleep(min(retry, max(0, deadline - time.monotonic())))
    return False


async def _database_probe():
    database = Database(os.environ['RAG_DATABASE_URL'])
    try:
        async with database.connection() as connection:
            await connection.execute(select(literal(1)))
    finally:
        await database.dispose()


def _group_signal(process, number):
    try:
        os.killpg(process.pid, number)
    except ProcessLookupError:
        pass


def _reap_descendants(processes):
    remaining = False
    for _, process in processes:
        # Popen must reap its direct child first, preserving its return code.
        if process.poll() is None:
            remaining = True
            continue
        while True:
            try:
                pid, _ = os.waitpid(-process.pid, os.WNOHANG)
            except ChildProcessError:
                break
            if pid == 0:
                remaining = True
                break
    return remaining


def _stop_processes(processes, settings):
    # Groups are retained even after their leader exits: a native child may
    # still be alive and becomes this launcher's child through subreaping.
    for _, process in reversed(processes):
        _group_signal(process, signal.SIGTERM)
    deadline = time.monotonic() + settings['shutdown_timeout_seconds']
    while _reap_descendants(processes) and time.monotonic() < deadline:
        time.sleep(min(settings['poll_seconds'], max(0, deadline - time.monotonic())))
    for _, process in reversed(processes):
        _group_signal(process, signal.SIGKILL)
    deadline = time.monotonic() + settings['kill_timeout_seconds']
    while _reap_descendants(processes):
        if time.monotonic() >= deadline:
            print('Backend shutdown failed: an owned process did not exit after SIGKILL', file=sys.stderr)
            return False
        time.sleep(min(settings['poll_seconds'], max(0, deadline - time.monotonic())))
    return True


def run_processes(commands, *, cwd, env, settings, stopping):
    # Generation already requires Linux. Subreaping lets us collect a native
    # grandchild even when its supervisor crashes before it can reap it.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), 'Cannot own backend descendant processes')
    processes = []
    result = 0
    try:
        for name, command in commands:
            if stopping.is_set():
                break
            process = subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True)
            processes.append((name, process))
            print(f'Backend started {name} (pid={process.pid})', flush=True)
        while processes and not stopping.is_set():
            for name, process in processes:
                code = process.poll()
                if code is not None:
                    print(f'Backend {name} exited unexpectedly (status={code})', file=sys.stderr, flush=True)
                    result = 1
                    stopping.set()
                    break
            stopping.wait(settings['poll_seconds'])
    except OSError:
        print('Backend could not start a component; check executable and working directory', file=sys.stderr)
        result = 1
    finally:
        if not _stop_processes(processes, settings):
            result = 1
    return result


def _check_resources(environment):
    for variable in ('RAG_MODEL_PATH', 'RAG_OCR_MODEL_PATH'):
        if not Path(environment[variable]).is_file():
            raise ConfigurationError(f'Missing model file for {variable}')
    for relative in ('tokenizer.json', 'model_quantized.onnx'):
        if not (Path(environment['RAG_E5_DIR']) / relative).is_file():
            raise ConfigurationError(f'Missing embedding resource: {relative}')
    ocr = Path(environment['RAG_OCR_DIR'])
    profiles = load_settings('ocr')
    files = ['dfine/config.json', 'dfine/preprocessor_config.json', 'dfine/model.onnx',
             profiles['printed']['model'], profiles['printed']['projector'], profiles['handwriting']['projector']]
    for relative in files:
        if not (ocr / relative).is_file():
            raise ConfigurationError(f'Missing OCR resource: {relative}')


def launch(config, environment):
    stopping = threading.Event()
    with stop_signals(stopping):
        for name in ('policy', 'runtime', 'ocr', 'documents', 'prompts'):
            load_settings(name)
        _check_resources(environment)
        database = config['database']
        print('Backend waiting for PostgreSQL', flush=True)
        try:
            ready = asyncio.run(wait_for_database(environment['RAG_DATABASE_URL'],
                timeout=database['ready_timeout_seconds'], retry=database['retry_seconds'],
                connect_timeout=database['connect_timeout_seconds'], stopping=stopping))
        except Exception:
            print('PostgreSQL readiness timed out or configuration is invalid; check database.dsn', file=sys.stderr)
            return 1
        if not ready:
            return 0
        env = os.environ.copy()
        env.update(environment)
        env['PYTHONUNBUFFERED'] = '1'
        commands = [
            ('documents', [sys.executable, '-m', 'app.document_worker']),
            ('generation', [sys.executable, '-m', 'app.generation']),
            ('api', [sys.executable, '-m', 'app.main', '--host', config['api']['host'], '--port', str(config['api']['port'])]),
        ]
        return run_processes(commands, cwd=resource_path('config').parent, env=env,
                             settings=config['supervisor'], stopping=stopping)


if __name__ == '__main__':
    if sys.argv[1:] != ['--database-probe']:
        raise SystemExit('Use backend/main.py to start the backend')
    try:
        asyncio.run(_database_probe())
    except Exception:
        raise SystemExit(1) from None
