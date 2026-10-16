"""Public policy contains only explicitly approved form constraints."""
from fastapi.testclient import TestClient

from app import main


def test_public_settings_uses_configured_limits_without_publishing_secrets(monkeypatch):
    inputs = {'email_min': 5, 'email_max': 150, 'password_min': 20,
              'password_max': 300, 'token_max': 96, 'filename_max': 180}
    monkeypatch.setattr(main, 'load_settings', lambda name: {
        'inputs': inputs | {'private_note': 'DO-NOT-PUBLISH'},
        'security': {'secret': 'DO-NOT-PUBLISH'},
    }, raising=False)
    # No application lifespan/DB or credential is needed for public form policy.
    client = TestClient(main.create_app())
    response = client.get('/api/public-settings')
    assert response.status_code == 200
    assert response.json() == {'inputs': inputs, 'document_formats': ['pdf', 'docx', 'txt', 'md']}
    assert 'DO-NOT-PUBLISH' not in response.text
    client.close()


def test_public_settings_reads_selected_local_policy_from_another_directory(tmp_path, monkeypatch):
    config = tmp_path / 'settings'
    config.mkdir()
    (config / 'policy.local.toml').write_text('[inputs]\nemail_min = 5\npassword_min = 20\nfilename_max = 180\n')
    monkeypatch.setenv('RAG_SERVICE_CONFIG', str(config / 'service.local.toml'))
    monkeypatch.chdir(tmp_path)
    client = TestClient(main.create_app())
    response = client.get('/api/public-settings')
    assert response.status_code == 200
    assert response.json()['inputs'] == {
        'email_min': 5, 'email_max': 254, 'password_min': 20,
        'password_max': 1024, 'token_max': 128, 'filename_max': 180,
    }
    client.close()
