"""Standard-library startup checks; native libraries live only in owned probes."""
from contextlib import contextmanager
import ctypes
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time


class BootstrapError(ValueError):
    pass


@contextmanager
def early_signals():
    previous = {number: signal.signal(number, signal.default_int_handler)
                for number in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield
    except KeyboardInterrupt:
        pass
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def _signal_group(pid, number):
    try:
        os.killpg(pid, number)
    except ProcessLookupError:
        pass


def _reap_group(process):
    if process.poll() is None:
        return False
    while True:
        try:
            pid, _ = os.waitpid(-process.pid, os.WNOHANG)
        except ChildProcessError:
            return True
        if pid == 0:
            return False


def run_owned(command, *, cwd=None, env=None, timeout=60):
    """Bound a probe/uv and all descendants, including after its leader exits."""
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # Linux PR_SET_CHILD_SUBREAPER
        raise BootstrapError('Cannot own startup probe descendants on this platform')
    with tempfile.TemporaryFile(mode='w+') as output:
        process = subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True,
                                   stdout=output, stderr=subprocess.STDOUT, text=True)
        try:
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise BootstrapError('Startup prerequisite check timed out; inspect the configured environment')
                time.sleep(.02)
            output.seek(0)
            return subprocess.CompletedProcess(command, process.returncode, output.read())
        finally:
            _signal_group(process.pid, signal.SIGTERM)
            deadline = time.monotonic() + .5
            while not _reap_group(process) and time.monotonic() < deadline:
                time.sleep(.02)
            _signal_group(process.pid, signal.SIGKILL)
            deadline = time.monotonic() + 2
            while not _reap_group(process):
                if time.monotonic() >= deadline:
                    raise BootstrapError('Owned startup process did not exit after SIGKILL')
                time.sleep(.02)


def dependency_issues(root):
    import tomllib
    with (Path(root) / 'pyproject.toml').open('rb') as stream:
        dependencies = tomllib.load(stream)['project']['dependencies']
    issues = []
    for requirement in dependencies:
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)(?:\[([^]]+)\])?==([^ ;]+)', requirement)
        if match is None:
            raise BootstrapError('Backend dependencies must retain exact pyproject versions')
        name, extras, wanted = match.groups()
        checks = [(name, wanted)]
        if name == 'psycopg' and extras:
            checks.extend((extra_name, wanted if extra == 'binary' else None)
                          for extra, extra_name in [('binary', 'psycopg-binary'), ('pool', 'psycopg-pool')]
                          if extra in extras.split(','))
        if name == 'sqlalchemy' and extras and 'asyncio' in extras.split(','):
            checks.append(('greenlet', None))
        for package, exact in checks:
            try:
                actual = metadata.version(package)
            except metadata.PackageNotFoundError:
                issues.append(f'{package} missing (required {exact or "extra"})')
            else:
                if exact and actual != exact:
                    issues.append(f'{package} {actual}; required {exact}')
    return issues


def native_fingerprint():
    try:
        distribution = metadata.distribution('llama-cpp-python')
    except metadata.PackageNotFoundError:
        return {}
    result = {}
    for item in distribution.files or ():
        if str(item).startswith('llama_cpp/lib/') and str(item).endswith('.so'):
            path = Path(distribution.locate_file(item))
            if path.is_file():
                with path.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256')
                result[path.name] = digest.hexdigest()
    return result


def _environment_report(python, root):
    if not Path(python).is_file() or not os.access(python, os.X_OK):
        return {'issues': ['launcher.python unavailable'], 'native': {}, 'isolated': True, 'python': [3, 12]}
    result = run_owned([str(python), str(Path(__file__).absolute()), '--check-environment', str(root)], cwd=root)
    if result.returncode:
        raise BootstrapError('launcher.python must run Python 3.12; prepare an isolated backend environment with uv sync --project backend --frozen')
    try:
        return json.loads(result.stdout)
    except (ValueError, TypeError):
        raise BootstrapError('Cannot inspect launcher.python; configure an isolated backend Python 3.12 environment') from None


def ensure_environment(python, root):
    root, python = Path(root), Path(python)
    before = _environment_report(python, root)
    if before['python'] != [3, 12]:
        raise BootstrapError('launcher.python requires Python 3.12; prepare backend/.venv with uv sync --project backend --frozen')
    if not before['isolated']:
        raise BootstrapError('launcher.python must belong to an isolated virtualenv; use backend/.venv/bin/python')
    if not before['issues']:
        return
    if os.environ.get('RAG_BOOTSTRAP_REPAIRED') == '1':
        raise BootstrapError('Dependencies invalid after one repair/re-exec; repair the configured environment explicitly')
    uv = shutil.which('uv')
    if uv is None:
        raise BootstrapError('Missing uv; install uv explicitly, then run uv sync --project backend --frozen. ' + '; '.join(before['issues']))
    environment = os.environ.copy()
    environment['UV_PROJECT_ENVIRONMENT'] = str(python.parent.parent)
    print('Backend preparing locked Python dependencies with uv', flush=True)
    result = run_owned([uv, 'sync', '--project', str(root), '--frozen'], cwd=root, env=environment, timeout=1800)
    after = _environment_report(python, root)
    if any(after['native'].get(name) != digest for name, digest in before['native'].items()):
        raise BootstrapError('Dependency repair changed existing llama native libraries; restore the known-compatible native build and verify generation/OCR before retrying')
    if result.returncode:
        raise BootstrapError('uv sync --project backend --frozen failed; inspect the isolated environment and locked native build requirements')
    if after['issues'] or after['python'] != [3, 12] or not after['isolated']:
        raise BootstrapError('Dependencies still invalid after one uv sync; no further repair attempted: ' + '; '.join(after['issues']))

    os.environ['RAG_BOOTSTRAP_REPAIRED'] = '1'


# This local CPU build was verified with actual generation, embedding and OCR.
# A different rebuild requires the same functional validation before adoption.
KNOWN_NATIVE = {
    'libggml-base.so': '31bc5513066bbe24aac11eaf98ae3ebd1bcaaaa94f8ff7d06ce94b9d19d1f232',
    'libggml-cpu.so': '3dc28deb691529573fd3fd850a7efdc3e595298e85a1fac3a15441104806b68a',
    'libggml.so': 'a2dc2170f27723f2c808f5a4bcb2c061dfef4ece170cba1a3e0984a4d381a15e',
    'libllama.so': 'bd4f0f7960973d3e5d7efa5a8c824ea4f233ac6bd18511faf115b27d7d907159',
    'libmtmd.so': '8b14e6b2096d6e687afae98d5aec1fb5011b9939432d89ebd56b631db7996bc3',
}


NATIVE_PROBE = '''import importlib
for name in ('alembic','fastapi','langgraph','langgraph.checkpoint.postgres','pgvector',
             'PIL.Image','psycopg','psycopg_pool','pypdfium2','sqlalchemy','greenlet','uvicorn'):
 importlib.import_module(name)
import psycopg
assert psycopg.pq.__impl__ == 'binary', 'psycopg binary extra unavailable'
import llama_cpp as native
from llama_cpp.llama_chat_format import MTMDChatHandler
from llama_cpp import mtmd_cpp
for name in ('llama_backend_init','llama_backend_free','llama_model_default_params',
 'llama_context_default_params','llama_model_load_from_file','llama_model_get_vocab',
 'llama_model_free','llama_tokenize','llama_init_from_model','llama_n_ctx',
 'llama_sampler_init_greedy','llama_sampler_sample','llama_sampler_free','llama_free',
 'llama_batch_init','llama_batch_free','llama_decode','llama_token_to_piece',
 'llama_vocab_is_eog','llama_set_abort_callback','ggml_abort_callback'):
 assert callable(getattr(native,name)), name
assert callable(mtmd_cpp.mtmd_default_marker)
assert mtmd_cpp.mtmd_default_marker(), 'MTMD marker unavailable'
assert callable(MTMDChatHandler)
native.llama_backend_init()
try:
 native.llama_model_default_params()
 native.llama_context_default_params()
finally:native.llama_backend_free()
import onnxruntime as ort
assert 'CPUExecutionProvider' in ort.get_available_providers()
assert callable(ort.InferenceSession)
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
assert Tokenizer(WordLevel({'[UNK]':0},unk_token='[UNK]')).encode('probe').ids == [0]
'''


def check_native(root, environment):
    if native_fingerprint() != KNOWN_NATIVE:
        raise BootstrapError('Unverified llama native build; restore the known-compatible CPU libraries. '
                             'A fresh rebuild needs functional generation and OCR verification before adoption')
    env = os.environ.copy()
    env.update(environment)
    result = run_owned([sys.executable, '-c', NATIVE_PROBE], cwd=root, env=env, timeout=60)
    if result.returncode:
        # No configuration values or inherited secrets are emitted by this probe.
        detail = result.stdout.strip().splitlines()[-1:] or [f'exit status {result.returncode}']
        raise BootstrapError('Native/import compatibility check failed: ' + detail[0] +
                             '; restore the known-compatible llama/MTMD/ONNX build. '
                             'An exact package version alone does not establish native compatibility')


if __name__ == '__main__':
    if sys.version_info[:2] != (3, 12):
        raise SystemExit('Backend requires Python 3.12 before reading TOML or importing the application')
    if len(sys.argv) != 3 or sys.argv[1] != '--check-environment':
        raise SystemExit('Use backend/main.py to start the backend')
    print(json.dumps({'python': list(sys.version_info[:2]), 'isolated': sys.prefix != sys.base_prefix,
                      'issues': dependency_issues(Path(sys.argv[2])), 'native': native_fingerprint()}))
