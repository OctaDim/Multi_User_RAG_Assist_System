"""Configured security profiles preserve saved credentials and policy behavior."""
import hashlib
from datetime import datetime, timezone

import pytest

from app import accounts
from app.auth import AccessError


def test_password_profile_change_keeps_original_credentials(tmp_path, monkeypatch):
    password = 'A durable previous password'
    salt = bytes(range(16))
    old_digest = hashlib.scrypt(password.encode(), salt=salt, n=131072, r=8, p=1, maxmem=268435456, dklen=32)
    previous = f'scrypt:131072:8:1:{salt.hex()}:{old_digest.hex()}'
    (tmp_path / 'policy.local.toml').write_text('[security]\nscrypt_n=65536\n')
    monkeypatch.setenv('RAG_SERVICE_CONFIG', str(tmp_path / 'service.local.toml'))
    encoded = accounts.hash_password(password)
    assert encoded.startswith('scrypt:65536:8:1:'), 'New credentials must use selected creation profile'
    assert accounts.verify_password(password, previous)
    assert accounts.verify_password(password, encoded)
    assert not accounts.verify_password('A wrong previous password', previous)
    assert not accounts.verify_password(password, 'scrypt:1073741824:8:1:00:00')
    assert not accounts.verify_password(password, 'malformed')


def test_email_domain_uses_selected_limit(tmp_path, monkeypatch):
    (tmp_path / 'policy.local.toml').write_text('[inputs]\nemail_max=20\n')
    monkeypatch.setenv('RAG_SERVICE_CONFIG', str(tmp_path / 'service.local.toml'))
    with pytest.raises(AccessError, match='invalid_email'):
        accounts.email_address('long-address@owned.test')
    assert accounts.email_address('a@owned.test') == 'a@owned.test'


async def test_session_and_verification_deadlines_use_policy(session, connection, environment, monkeypatch, tmp_path):
    from mailbox import Mailbox
    (tmp_path / 'service.local.toml').write_text('')
    (tmp_path / 'policy.local.toml').write_text('[accounts]\nsession_seconds=123\nverification_seconds=321\n')
    monkeypatch.setenv('RAG_SERVICE_CONFIG', str(tmp_path / 'service.local.toml'))
    with Mailbox() as mailbox:
        mailbox.configure(monkeypatch)
        started = datetime.now(timezone.utc)
        account = await accounts.register(session, 'configured@owned.test', 'A configured long password')
        row = await (await connection.execute('SELECT expires_at FROM email_verifications WHERE owner_id=%s', (account['id'],))).fetchone()
        assert 320 <= (row['expires_at']-started).total_seconds() <= 325
        await connection.execute('UPDATE accounts SET verified=true WHERE id=%s', (account['id'],))
        started = datetime.now(timezone.utc)
        logged_in = await accounts.login(session, 'configured@owned.test', 'A configured long password')
        row = await (await connection.execute('SELECT expires_at FROM sessions WHERE token_hash=%s', (accounts.secret_hash(logged_in['token']),))).fetchone()
        assert 122 <= (row['expires_at']-started).total_seconds() <= 126


async def test_ingestion_uses_configured_chunks_and_embedding_prefix(environment, rag_pool, connection, monkeypatch, tmp_path):
    import os
    from app.document_worker import DocumentWorker
    from app.rag import E5Embedder
    from app.main import create_app
    from live_http import LiveClient
    storage = tmp_path / 'originals'
    (tmp_path / 'service.local.toml').write_text('')
    (tmp_path / 'policy.local.toml').write_text('[ingestion]\nchunk_characters=50\n')
    prefix = 'passage: ' * 8
    (tmp_path / 'runtime.local.toml').write_text('[embedding]\nmax_length=32\npassage_prefix="' + prefix + '"\n')
    monkeypatch.setenv('RAG_SERVICE_CONFIG', str(tmp_path / 'service.local.toml'))
    monkeypatch.setenv('RAG_DATABASE_URL', environment['dsn'])
    monkeypatch.setenv('RAG_ORIGINALS_DIR', str(storage))
    content = 'я ' * 120
    headers = {'Authorization': 'Bearer ' + environment['user']['token']}
    with LiveClient(create_app()) as client:
        response = client.post('/api/documents/uploads', headers=headers, json={'files': [{'name': 'chunks.txt', 'size': len(content.encode())}]})
        assert response.status_code == 201
        identity = response.json()['documents'][0]['id']
        assert client.put(f'/api/documents/{identity}/original', headers=headers, content=content.encode()).status_code == 200
        worker = DocumentWorker(rag_pool, E5Embedder(os.environ['RAG_E5_DIR']))
        assert await worker.process_one()
        chunks = await (await connection.execute('SELECT text,span_start,span_end FROM source_chunks c JOIN documents d ON d.published_revision=c.revision_id WHERE d.id=%s ORDER BY span_start', (identity,))).fetchall()
    assert ''.join(row['text'] for row in chunks) == content
    assert all(len(row['text']) <= 50 for row in chunks)
    assert all(not worker.embedder.tokenizer.encode(prefix + row['text']).overflowing for row in chunks)
    assert all(content[row['span_start']:row['span_end']] == row['text'] for row in chunks)


async def test_generation_reaps_stubborn_child_using_configured_timeout(tmp_path, monkeypatch):
    import subprocess
    import sys
    import time
    from app.generation import Supervisor
    (tmp_path / 'policy.local.toml').write_text('[generation]\nreap_timeout_seconds=0.05\n')
    monkeypatch.setenv('RAG_SERVICE_CONFIG', str(tmp_path / 'service.local.toml'))
    child = subprocess.Popen([sys.executable, '-u', '-c',
        'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print("ready"); time.sleep(30)'],
        stdout=subprocess.PIPE, text=True)
    supervisor = Supervisor('')
    supervisor.child = child
    with (tmp_path / 'fence').open('w+b') as fence:
        supervisor.fence = fence.fileno()
        try:
            assert child.stdout.readline().strip() == 'ready'
            started = time.monotonic()
            await supervisor.reap_child()
            elapsed = time.monotonic() - started
            assert child.returncode < 0 and supervisor.child is None
            assert 0.04 <= elapsed < 2, elapsed
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
            child.stdout.close()
