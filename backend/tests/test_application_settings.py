"""Installation profiles must change behavior without exposing their contents in errors."""
import hashlib

import pytest

from app import configuration


def test_profiles_follow_selected_service_directory_from_other_cwd(tmp_path, monkeypatch):
    local = tmp_path / 'installation'
    local.mkdir()
    (local / 'policy.local.toml').write_text('[inputs]\npassword_min = 20\n')
    monkeypatch.setenv('RAG_SERVICE_CONFIG', str(local / 'service.local.toml'))
    monkeypatch.chdir(tmp_path)
    assert hasattr(configuration, 'load_settings'), 'Named application profiles need the same override owner as service config'
    config = configuration.load_settings('policy')
    assert config['inputs']['password_min'] == 20
    assert config['inputs']['password_max'] == 1024
    config['inputs']['password_min'] = 999
    assert configuration.load_settings('policy')['inputs']['password_min'] == 20


@pytest.mark.parametrize('body,key', [
    ('[inputs]\npassword_min = "PRIVATE_VALUE"', 'inputs.password_min'),
    ('[inputs]\npassword_min = 2048', 'inputs.password'),
    ('[tabs]\nheartbeat_seconds = 30', 'tabs.heartbeat_seconds'),
    ('[security]\nscrypt_n = 123', 'security.scrypt_n'),
    ('[inputs]\nunknown = "PRIVATE_VALUE"', 'inputs.unknown'),
])
def test_invalid_policy_rejected_without_value_disclosure(tmp_path, monkeypatch, body, key):
    (tmp_path / 'policy.local.toml').write_text(body)
    monkeypatch.setenv('RAG_SERVICE_CONFIG', str(tmp_path / 'service.local.toml'))
    assert hasattr(configuration, 'load_settings'), 'Named application profiles must be validated'
    with pytest.raises(configuration.ConfigurationError) as error:
        configuration.load_settings('policy')
    assert key in str(error.value)
    assert 'PRIVATE_VALUE' not in str(error.value)


def test_context_budget_must_fit_configured_context(tmp_path, monkeypatch):
    (tmp_path / 'runtime.local.toml').write_text('[generation]\nn_ctx=128\n')
    monkeypatch.setenv('RAG_SERVICE_CONFIG', str(tmp_path / 'service.local.toml'))
    assert hasattr(configuration, 'load_settings')
    with pytest.raises(configuration.ConfigurationError, match='rag.response_reserve'):
        configuration.load_settings('runtime')


def test_original_model_prompt_bytes_are_preserved():
    assert hashlib.sha256(configuration.load_settings('prompts')['rag']['system'].encode()).hexdigest() == 'f39a58a3906572ae6f1d15ba3f5c62bba7266ed96e18d973191c509b5b26212c'
    assert hashlib.sha256(configuration.load_settings('prompts')['rag']['template'].encode()).hexdigest() == 'f556ba7ef5ef8cda360fa956786a5b4069686aa11a73de0e577c36cfc259dcfe'
    assert hashlib.sha256(configuration.load_settings('prompts')['ocr']['printed'].encode()).hexdigest() == '174efa2abedd22b06af3c2ff5bb39c89487e402b42fc672287ca6ca4a203131e'
    assert hashlib.sha256(configuration.load_settings('prompts')['ocr']['handwriting'].encode()).hexdigest() == 'd1c7bce2e11724f2d06432beff8e2fb2d47e877fc55f8898164ab6d547239246'


@pytest.mark.parametrize('profile,body,key', [
    ('policy', '[security]\nscrypt_maxmem=2147483648', 'security.scrypt_maxmem'),
    ('policy', '[tabs]\npoll_seconds=20.0', 'tabs.poll_seconds'),
    ('policy', '[inputs]\npassword_max=2147483648', 'inputs.password_max'),
    ('runtime', '[rag]\nretrieval_limit=100', 'rag.retrieval_limit'),
    ('runtime', '[generation]\nn_ctx=4294967297', 'generation.n_ctx'),
    ('runtime', '[generation]\nn_threads=2147483648', 'generation.n_threads'),
    ('ocr', '[execution]\nn_threads=2147483648', 'execution.n_threads'),
    ('ocr', '[execution]\nn_batch=64\nn_ubatch=128', 'execution.n_ubatch'),
    ('ocr', '[fragments]\nlimit=200\noverlap=128', 'fragments.overlap'),
    ('prompts', '[rag]\ntemplate="{system} {question.secret}"', 'rag.template'),
])
def test_invalid_cross_field_and_native_bounds(tmp_path, monkeypatch, profile, body, key):
    (tmp_path / f'{profile}.local.toml').write_text(body)
    monkeypatch.setenv('RAG_SERVICE_CONFIG', str(tmp_path / 'service.local.toml'))
    with pytest.raises(configuration.ConfigurationError, match=key):
        configuration.load_settings(profile)
