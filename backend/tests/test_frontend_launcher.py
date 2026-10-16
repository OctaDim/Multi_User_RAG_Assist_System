from contextlib import contextmanager
import importlib.util
from pathlib import Path
import subprocess
import sys
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest


FRONTEND = Path(__file__).parents[2] / 'frontend'
spec = importlib.util.spec_from_file_location('rag_frontend_main', FRONTEND / 'main.py')
frontend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frontend)


@contextmanager
def served(config):
    server = frontend.create_server(config)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_public_config_injection_and_head(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = frontend.load_config()
    config['server']['port'] = 0
    config['api']['origin'] = 'https://api.example.test:9443'
    config['client']['reconnect_ms'] = 2345
    config['ui'] = {'composer_rows': 7, 'correction_rows': 18, 'short_id_chars': 10}
    with served(config) as origin:
        with urlopen(origin) as response:
            body = response.read()
            assert b'content="https://api.example.test:9443"' in body
            assert b'content="2345"' in body
            assert b'content="18"' in body
            assert b'content="10"' in body
            assert b'id="question" rows="7"' in body
            assert b'id="authentication" inert' in body
        with urlopen(Request(origin, method='HEAD')) as response:
            assert response.read() == b''
            assert int(response.headers['Content-Length']) == len(body)
        with urlopen(origin + '/src/api.js') as response:
            assert 'javascript' in response.headers['Content-Type']


@pytest.mark.parametrize('key,value', [('composer_rows', 0), ('correction_rows', True), ('short_id_chars', -2)])
def test_ui_config_rejects_invalid_values(key, value):
    config = frontend.load_config()
    config.setdefault('ui', {})[key] = value
    with pytest.raises(ValueError, match=f'ui.{key}'):
        frontend.validate_config(config)


def test_ui_local_settings_are_independent_of_working_directory(tmp_path, monkeypatch):
    local = tmp_path / 'service.local.toml'
    local.write_text('[ui]\ncomposer_rows = 7\ncorrection_rows = 18\nshort_id_chars = 10\n')
    monkeypatch.chdir(tmp_path)
    config = frontend.load_config(local)
    frontend.validate_config(config)
    assert config['ui'] == {'composer_rows': 7, 'correction_rows': 18, 'short_id_chars': 10}


@pytest.mark.parametrize('path', [
    '/config/service.toml', '/config/service.local.toml', '/main.py',
    '/backend/config/service.local.toml', '/src/../config/service.toml',
    '/src/%2e%2e/config/service.toml', '/src/', '/src/not-allowed.txt',
])
@pytest.mark.parametrize('method', ['GET', 'HEAD'])
def test_only_public_files_are_served(path, method):
    config = frontend.load_config()
    config['server']['port'] = 0
    with served(config) as origin:
        with pytest.raises(HTTPError) as error:
            urlopen(Request(origin + path, method=method))
        assert error.value.code == 404


def test_frontend_main_reports_busy_port_from_foreign_directory(tmp_path):
    config = frontend.load_config()
    config['server']['port'] = 0
    with served(config) as origin:
        port = int(origin.rsplit(':', 1)[1])
        local = tmp_path / 'frontend.toml'
        local.write_text(f'[server]\nport = {port}\n')
        result = subprocess.run([sys.executable, str(FRONTEND / 'main.py'), '--config', str(local)],
                                cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert 'Frontend startup failed' in result.stderr


@pytest.mark.parametrize('section,key,value', [
    ('client', 'reconnect_ms', 2147483648),
    ('ui', 'composer_rows', 4294967296),
    ('ui', 'correction_rows', 4294967296),
])
def test_frontend_config_rejects_browser_integer_overflow(section, key, value):
    config = frontend.load_config()
    config[section][key] = value
    with pytest.raises(ValueError, match=f'{section}.{key}'):
        frontend.validate_config(config)
