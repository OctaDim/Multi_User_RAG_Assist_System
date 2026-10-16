"""Early checks must fail before component imports and own disposable children."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

BACKEND = Path(__file__).parents[1]


def bootstrap_module():
    spec = importlib.util.spec_from_file_location('startup_bootstrap', BACKEND / 'bootstrap.py')
    assert spec is not None and Path(spec.origin).is_file(), 'Missing stdlib startup bootstrap'
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_checks_models_before_importing_launcher(tmp_path):
    # Inject only the expensive boundaries. Real main argument/config flow runs.
    script = '''import importlib.util,sys,types
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import app.configuration as configuration
configuration.load_service_config=lambda selected: {'launcher':{'python':sys.executable}}
configuration.launch_environment=lambda config: {}
configuration.section_path=lambda value: Path(value)
models=types.ModuleType('app.model_artifacts')
class ModelArtifactError(ValueError):pass
models.ModelArtifactError=ModelArtifactError
def verify(config):raise ModelArtifactError('Missing model artifact: fixture; run prepare_models.py')
models.verify_installation=verify
sys.modules['app.model_artifacts']=models
launcher=types.ModuleType('app.launcher')
launcher.launch=lambda *args: 42
sys.modules['app.launcher']=launcher
try:
 import bootstrap
 bootstrap.ensure_environment=lambda *args: None
 bootstrap.check_native=lambda *args: None
except ImportError:pass
spec=importlib.util.spec_from_file_location('entry',Path(sys.argv[1])/'main.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
sys.argv=['main.py']
raise SystemExit(module.main())
'''
    result = subprocess.run([sys.executable, '-c', script, str(BACKEND)], capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    assert 'Missing model artifact' in result.stderr
    assert 'prepare_models.py' in result.stderr


def test_dependency_checks_include_exact_direct_versions_and_binary_extras(tmp_path, monkeypatch):
    bootstrap = bootstrap_module()
    (tmp_path / 'pyproject.toml').write_text('[project]\ndependencies=["fastapi==1.2", "psycopg[binary,pool]==3.3.6"]\n')
    versions = {'fastapi': '1.1', 'psycopg': '3.3.6', 'psycopg-pool': '3.3.0'}
    def version(name):
        if name not in versions:
            raise bootstrap.metadata.PackageNotFoundError(name)
        return versions[name]
    monkeypatch.setattr(bootstrap.metadata, 'version', version)
    issues = bootstrap.dependency_issues(tmp_path)
    assert any('fastapi' in item and '1.2' in item for item in issues)
    assert any('psycopg-binary' in item for item in issues)
    assert not any('psycopg-pool' in item for item in issues)


@pytest.mark.parametrize('outcome', ['success', 'still-missing', 'sync-failed', 'no-uv', 'native-changed'])
def test_environment_repair_is_frozen_isolated_and_bounded(tmp_path, monkeypatch, outcome):
    bootstrap = bootstrap_module()
    monkeypatch.setenv('RAG_BOOTSTRAP_REPAIRED','')
    python = tmp_path / '.venv/bin/python'
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    reports = [dict(issues=['fastapi missing'], native={'libllama.so':'old'}, isolated=True, python=[3,12])]
    reports.append(dict(issues=[] if outcome != 'still-missing' else ['fastapi missing'],
                        native={'libllama.so':'changed' if outcome == 'native-changed' else 'old'},
                        isolated=True, python=[3,12]))
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        if '--check-environment' in command:
            return subprocess.CompletedProcess(command, 0, json.dumps(reports.pop(0)))
        assert command == ['/fixture/uv', 'sync', '--project', str(tmp_path), '--frozen']
        assert kwargs['env']['UV_PROJECT_ENVIRONMENT'] == str(tmp_path / '.venv')
        return subprocess.CompletedProcess(command, 1 if outcome == 'sync-failed' else 0, '')
    monkeypatch.setattr(bootstrap, 'run_owned', run)
    monkeypatch.setattr(bootstrap.shutil, 'which', lambda name: None if outcome == 'no-uv' else '/fixture/uv')
    if outcome == 'success':
        bootstrap.ensure_environment(python, tmp_path)
    else:
        with pytest.raises(bootstrap.BootstrapError):
            bootstrap.ensure_environment(python, tmp_path)
    assert sum('sync' in command for command, _ in calls) <= 1
    assert len(reports) == (1 if outcome == 'no-uv' else 0)


@pytest.mark.parametrize('stop_signal', [signal.SIGINT, signal.SIGTERM])
def test_early_child_signal_reaps_owned_group_and_preserves_unrelated(tmp_path, stop_signal):
    bootstrap_module()
    record = tmp_path / 'pids'
    child = '''import os,signal,subprocess,sys,time
from pathlib import Path
p=subprocess.Popen([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(120)'])
Path(sys.argv[1]).write_text(str(os.getpid())+','+str(p.pid))
while True:time.sleep(1)
'''
    command = '''import sys
from bootstrap import early_signals,run_owned
with early_signals():
 run_owned([sys.executable,'-c',sys.argv[1],sys.argv[2]],timeout=120)
'''
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(120)'])
    process = subprocess.Popen([sys.executable,'-c',command,child,str(record)],cwd=BACKEND,
                               stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    owned = []
    try:
        deadline = time.monotonic() + 8
        while not record.exists():
            assert process.poll() is None, process.communicate()
            assert time.monotonic() < deadline
            time.sleep(.02)
        owned = [int(pid) for pid in record.read_text().split(',')]
        process.send_signal(stop_signal)
        assert process.wait(8) == 0, process.communicate()
        assert all(not Path(f'/proc/{pid}').exists() for pid in owned)
        assert unrelated.poll() is None
    finally:
        for child_process in (process, unrelated):
            if child_process.poll() is None:
                child_process.kill()
            child_process.wait()
        for pid in owned:
            try:os.kill(pid,signal.SIGKILL)
            except ProcessLookupError:pass


@pytest.mark.parametrize('section,version,required', [('backend',(3,10,0),'3.12'), ('frontend',(3,10,0),'3.11')])
def test_unsupported_python_fails_before_tomllib_import(section, version, required):
    script = '''import builtins,runpy,sys
original=builtins.__import__
def checked(name,*args,**kwargs):
 if name=='tomllib' or name.startswith('app.'):
  raise RuntimeError('application/TOML imported before Python check')
 return original(name,*args,**kwargs)
builtins.__import__=checked
sys.version_info=(3,10,0)
runpy.run_path(sys.argv[1],run_name='__main__')
'''
    result = subprocess.run([sys.executable,'-c',script,str(BACKEND.parent / section / 'main.py')],capture_output=True,text=True)
    assert result.returncode != 0
    assert required in result.stderr
    assert 'RuntimeError' not in result.stderr
    assert 'Traceback' not in result.stderr


def test_failed_reexec_environment_does_not_trigger_second_sync(tmp_path, monkeypatch):
    bootstrap = bootstrap_module()
    monkeypatch.setenv('RAG_BOOTSTRAP_REPAIRED','1')
    monkeypatch.setattr(bootstrap,'_environment_report',lambda *args: dict(
        issues=['dependency missing'],native={},isolated=True,python=[3,12]))
    def forbidden(*args, **kwargs):
        pytest.fail('A re-executed bootstrap must not repeat uv sync')
    monkeypatch.setattr(bootstrap,'run_owned',forbidden)
    with pytest.raises(bootstrap.BootstrapError,match='repair'):
        bootstrap.ensure_environment(tmp_path / '.venv/bin/python',tmp_path)


def test_unverified_native_rebuild_is_not_blessed_by_successful_symbol_probe(tmp_path, monkeypatch):
    bootstrap = bootstrap_module()
    monkeypatch.setattr(bootstrap,'native_fingerprint',lambda: {'libllama.so':'unverified-build'})
    monkeypatch.setattr(bootstrap,'run_owned',lambda *args,**kwargs: subprocess.CompletedProcess(args,0,''))
    with pytest.raises(bootstrap.BootstrapError,match='known-compatible'):
        bootstrap.check_native(tmp_path,{})


def test_failed_sync_still_detects_changed_existing_native_libraries(tmp_path, monkeypatch):
    bootstrap = bootstrap_module()
    monkeypatch.setenv('RAG_BOOTSTRAP_REPAIRED','')
    reports = iter([
        dict(issues=['fastapi missing'],native={'libllama.so':'old'},isolated=True,python=[3,12]),
        dict(issues=['fastapi missing'],native={'libllama.so':'changed'},isolated=True,python=[3,12]),
    ])
    monkeypatch.setattr(bootstrap,'_environment_report',lambda *args: next(reports))
    monkeypatch.setattr(bootstrap.shutil,'which',lambda *args: '/fixture/uv')
    monkeypatch.setattr(bootstrap,'run_owned',lambda *args,**kwargs: subprocess.CompletedProcess(args,1,''))
    with pytest.raises(bootstrap.BootstrapError,match='changed existing llama native'):
        bootstrap.ensure_environment(tmp_path / '.venv/bin/python',tmp_path)


def test_main_import_keeps_native_and_database_dependencies_unloaded():
    result = subprocess.run([sys.executable,'-c','''import importlib.util,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
spec=importlib.util.spec_from_file_location('backend_entry',Path(sys.argv[1])/'main.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
print(json.dumps(sorted(name for name in sys.modules if name.split('.')[0] in
 {'numpy','onnxruntime','langgraph','llama_cpp','psycopg','sqlalchemy'} or name in {'app.main','app.launcher','app.rag'})))
''',str(BACKEND)],capture_output=True,text=True,check=True)
    assert json.loads(result.stdout) == []


def test_real_environment_probe_and_fake_uv_recheck_missing_dependency(tmp_path, monkeypatch):
    bootstrap = bootstrap_module()
    monkeypatch.setenv('RAG_BOOTSTRAP_REPAIRED','')
    root = tmp_path / 'backend'
    root.mkdir()
    python = root / '.venv/bin/python'
    subprocess.run([sys.executable,'-m','venv','--without-pip',str(root / '.venv')],check=True)
    (root / 'pyproject.toml').write_text('[project]\ndependencies=["fixture-package==1.2.3"]\n')
    uv = tmp_path / 'uv'
    record = tmp_path / 'uv-call.json'
    uv.write_text('#!' + sys.executable + '\n' + '''import json,os,sys
from pathlib import Path
root=Path(sys.argv[3])
assert sys.argv[1:3]==['sync','--project'] and sys.argv[4:]==['--frozen']
assert os.environ['UV_PROJECT_ENVIRONMENT']==str(root/'.venv')
Path(''' + repr(str(record)) + ''').write_text(json.dumps(sys.argv[1:]))
metadata=root/'.venv/lib/python3.12/site-packages/fixture_package-1.2.3.dist-info'
metadata.mkdir()
(metadata/'METADATA').write_text('Metadata-Version: 2.1\\nName: fixture-package\\nVersion: 1.2.3\\n')
''')
    uv.chmod(0o755)
    monkeypatch.setattr(bootstrap.shutil,'which',lambda name: str(uv))
    with bootstrap.early_signals():
        bootstrap.ensure_environment(python,root)
    assert json.loads(record.read_text()) == ['sync','--project',str(root),'--frozen']
    # Healthy environment must succeed even after the uv executable is removed.
    uv.unlink()
    with bootstrap.early_signals():
        bootstrap.ensure_environment(python,root)


@pytest.mark.parametrize('mode', ['timeout', 'leader-exit'])
def test_owned_probe_reaps_descendants_after_timeout_or_leader_exit(tmp_path, mode):
    record = tmp_path / 'owned-pids'
    child = '''import os,subprocess,sys,time
from pathlib import Path
ready=Path(sys.argv[1]+'.ready')
p=subprocess.Popen([sys.executable,'-c',
 'import signal,sys,time;from pathlib import Path;signal.signal(signal.SIGTERM,signal.SIG_IGN);Path(sys.argv[1]).write_text("ready");time.sleep(120)',str(ready)])
while not ready.exists():time.sleep(.01)
Path(sys.argv[1]).write_text(str(os.getpid())+','+str(p.pid))
if sys.argv[2]=='leader-exit':raise SystemExit(0)
while True:time.sleep(1)
'''
    command = '''import sys
from bootstrap import BootstrapError,run_owned
try:
 result=run_owned([sys.executable,'-c',sys.argv[1],sys.argv[2],sys.argv[3]],timeout=1)
except BootstrapError as error:
 assert sys.argv[3]=='timeout' and 'timed out' in str(error),str(error)
else:
 assert sys.argv[3]=='leader-exit' and result.returncode==0
'''
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(120)'])
    try:
        result = subprocess.run([sys.executable, '-c', command, child, str(record), mode],
                                cwd=BACKEND, capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        owned = [int(pid) for pid in record.read_text().split(',')]
        assert all(not Path(f'/proc/{pid}').exists() for pid in owned)
        assert unrelated.poll() is None
    finally:
        if unrelated.poll() is None:
            unrelated.kill()
        unrelated.wait()
        if record.exists():
            for pid in map(int, record.read_text().split(',')):
                try:os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:pass
