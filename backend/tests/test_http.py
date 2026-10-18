from live_http import LiveClient as TestClient
from app.main import app


def test_http_rejects_missing_credentials_and_restart_only_settings(environment, monkeypatch):
    monkeypatch.setenv("RAG_DATABASE_URL", environment["dsn"])
    with TestClient(app) as client:
        response = client.get(f"/api/conversations/{environment['conversation']}")
        assert response.status_code == 401
        assert response.json() == {"error": "unauthenticated"}
        response = client.patch("/api/settings", json={"n_threads": 8}, headers={"Authorization": f"Bearer {environment['super_admin']['token']}"})
        assert response.status_code == 422
        assert response.json() == {"error": "invalid_settings"}
        assert client.get("/api/settings", headers={"Authorization": f"Bearer {environment['super_admin']['token']}"}).json()["revision"] == 0


def test_http_accepts_one_question_replays_ack_and_stops(environment, monkeypatch):
    from uuid import uuid4

    monkeypatch.setenv("RAG_DATABASE_URL", environment["dsn"])
    headers = {"Authorization": f"Bearer {environment['user']['token']}", "X-Tab-Proof": environment["proof"]}
    payload = {"operation_key": str(uuid4()), "question": "HTTP question", "document_ids": [str(environment["document"])], "tab_id": str(environment["tab"])}
    route = f"/api/conversations/{environment['conversation']}/answers"
    with TestClient(app) as client:
        first = client.post(route, json=payload, headers=headers)
        assert first.status_code == 200
        request_id = first.json()["id"]
        assert client.post(route, json=payload, headers=headers).json()["id"] == request_id
        payload["operation_key"] = str(uuid4())
        assert client.post(route, json=payload, headers=headers).status_code == 409
        stopped = client.post(f"/api/answers/{request_id}/stop", headers=headers)
        assert stopped.status_code == 200 and stopped.json()["state"] == "interrupted"
        history = client.get(f"/api/conversations/{environment['conversation']}", headers=headers).json()
        assert [message["text"] for message in history["messages"]] == ["HTTP question"]


def test_api_lifespan_restart_preserves_overrides_and_applied_revision(environment, monkeypatch):
    monkeypatch.setenv("RAG_DATABASE_URL", environment["dsn"])
    headers = {"Authorization": f"Bearer {environment['super_admin']['token']}"}
    with TestClient(app) as client:
        saved = client.patch("/api/settings", json={"max_active": 6}, headers=headers)
        assert saved.status_code == 200 and saved.json()["revision"] == 1
    with TestClient(app) as restarted:
        values = restarted.get("/api/settings", headers=headers).json()
        assert values["values"]["max_active"] == 6 and values["revision"] == 1
        assert values["applied_revision"] == 0


def test_login_preflight_is_public_and_keeps_exact_cors_origin(environment,monkeypatch):
    from app.main import create_app
    monkeypatch.setenv('RAG_DATABASE_URL',environment['dsn'])
    monkeypatch.setenv('RAG_FRONTEND_ORIGIN','http://127.0.0.1:54321')
    with TestClient(create_app()) as client:
        response=client.options('/api/accounts/login',headers={'Origin':'http://127.0.0.1:54321',
            'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type'})
        assert response.status_code==200
        assert response.headers['access-control-allow-origin']=='http://127.0.0.1:54321'
        assert response.text=='OK'


def test_forwarded_loopback_origins_require_explicit_opt_in(environment, monkeypatch):
    from app.main import create_app
    monkeypatch.setenv('RAG_DATABASE_URL', environment['dsn'])
    monkeypatch.setenv('RAG_FRONTEND_ORIGIN', 'http://localhost:55848')
    for enabled in ('0', '1'):
        monkeypatch.setenv('RAG_ALLOW_LOOPBACK_ORIGINS', enabled)
        with TestClient(create_app()) as client:
            for origin in ('http://localhost:56914', 'http://127.0.0.1:54321', 'http://[::1]:54321'):
                response = client.get('/api/public-settings', headers={'Origin': origin})
                assert response.status_code == 200
                assert response.headers.get('access-control-allow-origin') == (origin if enabled == '1' else None)
                preflight = client.options('/api/accounts/login', headers={
                    'Origin': origin, 'Access-Control-Request-Method': 'POST',
                    'Access-Control-Request-Headers': 'content-type,authorization',
                })
                assert preflight.status_code == (200 if enabled == '1' else 400)
            for origin in ('https://external.example', 'http://localhost.evil.test:56914',
                           'http://127.0.0.1.evil.test:56914', 'http://192.168.1.2:56914', 'null'):
                response = client.get('/api/public-settings', headers={'Origin': origin})
                assert 'access-control-allow-origin' not in response.headers
