from pathlib import Path

import pytest

from app.configuration import ConfigurationError, launch_environment, load_service_config, section_path


def test_local_settings_override_defaults_and_paths_are_section_relative(tmp_path, monkeypatch):
    local = tmp_path / 'service.local.toml'
    local.write_text('''[api]
port = 9123
[database]
dsn = "host=db.example dbname=owned user=owned"
[models]
generation = "models/model.gguf"
embedding = "models/e5"
ocr = "models/ocr"
''')
    monkeypatch.chdir(tmp_path)
    config = load_service_config(local)
    environment = launch_environment(config)
    assert config['api']['port'] == 9123
    assert environment['RAG_DATABASE_URL'] == 'host=db.example dbname=owned user=owned'
    assert Path(environment['RAG_MODEL_PATH']) == Path(__file__).parents[1] / 'models/model.gguf'
    assert Path(environment['RAG_ORIGINALS_DIR']).is_absolute()


def test_missing_required_setting_does_not_echo_secrets():
    config = load_service_config()
    config['database']['dsn'] = ''
    config['smtp']['password'] = 'must-not-appear-in-diagnostic'
    with pytest.raises(ConfigurationError, match='database.dsn') as error:
        launch_environment(config)
    assert 'must-not-appear' not in str(error.value)


@pytest.mark.parametrize('section,key,value', [
    ('api', 'port', 65536), ('api', 'port', True),
    ('api', 'frontend_origin', 'https://example.test/path'),
    ('api', 'allow_loopback_origins', 'true'),
    ('supervisor', 'poll_seconds', 0),
])
def test_invalid_settings_rejected(section, key, value):
    config = load_service_config()
    config[section][key] = value
    with pytest.raises(ConfigurationError, match=f'{section}.{key}'):
        launch_environment(config)


def test_interpreter_path_is_normalized_without_resolving_virtualenv_symlink():
    expected = Path(__file__).parents[1] / '.venv/bin/python'
    assert section_path('../backend/.venv/bin/python') == expected
    assert section_path(str(expected.parent / '../bin/python')) == expected


def test_loopback_cors_opt_in_is_exported_to_component_environment():
    config = load_service_config()
    for enabled, expected in ((False, '0'), (True, '1')):
        config['api']['allow_loopback_origins'] = enabled
        assert launch_environment(config)['RAG_ALLOW_LOOPBACK_ORIGINS'] == expected
