from urllib.parse import parse_qs, urlsplit
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from live_http import LiveClient as TestClient
import pytest
from app import accounts, answers, events
from app.auth import AccessError, principal, secret_hash
from app.generation import Coordinator
from app.main import create_app
from app.rag import GuardedSaver
from mailbox import Mailbox


def credentials(email='new-user@owned.test'):
    return {'email': email, 'password': 'A long owned test password'}


def proof(mailbox, email):
    return parse_qs(urlsplit(mailbox.link(email)).fragment)['verify'][0]


def signup(client, mailbox, email, invitation=None):
    body = credentials(email)
    if invitation:
        body['invitation'] = invitation
    registered = client.post('/api/accounts/register', json=body)
    assert registered.status_code == 201
    assert client.post('/api/accounts/verify', json={'token': proof(mailbox, email)}).status_code == 200
    logged_in = client.post('/api/accounts/login', json=credentials(email))
    assert logged_in.status_code == 200
    return registered.json(), {'Authorization': f"Bearer {logged_in.json()['token']}"}


@pytest.fixture
def account_client(environment, monkeypatch):
    monkeypatch.setenv('RAG_DATABASE_URL', environment['dsn'])
    with Mailbox() as mailbox:
        mailbox.configure(monkeypatch)
        with TestClient(create_app()) as client:
            yield client, mailbox


def test_real_registration_mail_verification_and_login(environment, monkeypatch):
    monkeypatch.setenv('RAG_DATABASE_URL', environment['dsn'])
    with Mailbox() as mailbox:
        mailbox.configure(monkeypatch)
        with TestClient(create_app()) as client:
            credentials = {'email': 'new-user@owned.test', 'password': 'A long owned test password'}
            registered = client.post('/api/accounts/register', json=credentials)
            assert registered.status_code == 201
            assert 'token' not in registered.text and 'password' not in registered.text
            assert client.post('/api/accounts/login', json=credentials).status_code == 403
            verification = parse_qs(urlsplit(mailbox.link(credentials['email'])).fragment)['verify'][0]
            assert client.post('/api/accounts/verify', json={'token': verification}).status_code == 200
            assert client.post('/api/accounts/verify', json={'token': verification}).status_code == 400
            logged_in = client.post('/api/accounts/login', json=credentials)
            assert logged_in.status_code == 200
            headers = {'Authorization': f"Bearer {logged_in.json()['token']}"}
            me = client.get('/api/accounts/me', headers=headers).json()
            assert me['account']['role'] == 'user' and me['account']['verified']
            assert len(me['conversations']) == 1
            history = client.get(f"/api/conversations/{me['conversations'][0]['id']}", headers=headers).json()
            assert history['messages'] == []
            assert client.post('/api/accounts/logout', headers=headers).status_code == 200
            assert client.get('/api/accounts/me', headers=headers).status_code == 401


def test_passwords_validation_roles_and_credentials_do_not_leak(account_client):
    client, mailbox = account_client
    body = credentials()
    for changes in ({'password': 'short-secret'}, {'role': 'super_admin'}, {'email': 'bad\r\nBcc: victim@example.com'}):
        result = client.post('/api/accounts/register', json=body | changes)
        assert result.status_code == 422
        assert 'password' not in result.text and 'short-secret' not in result.text
    account, headers = signup(client, mailbox, body['email'])
    assert account['role'] == 'user' and not account['paid']
    assert client.post('/api/accounts/login', json=body | {'password': 'Wrong owned test password'}).status_code == 401
    assert client.post('/api/accounts/login', json=body | {'email': 'absent@owned.test'}).status_code == 401
    assert client.post('/api/accounts/register', json=body).status_code == 409
    assert client.patch(f"/api/accounts/{account['id']}", json={'role': 'super_admin'}, headers=headers).status_code == 403
    assert client.get('/api/accounts', headers=headers).status_code == 403
    assert client.get('/api/settings', headers=headers).status_code == 403
    for response in (client.get('/api/accounts/me', headers=headers), client.patch(f"/api/accounts/{account['id']}", json={'password_hash': 'injected'}, headers=headers)):
        assert 'scrypt' not in response.text and 'A long owned test password' not in response.text


async def test_verification_expiry_resend_and_block_are_independent(account_client, connection, environment):
    client, mailbox = account_client
    body = credentials('blocked@owned.test')
    account = client.post('/api/accounts/register', json=body).json()
    old = proof(mailbox, body['email'])
    await connection.execute("UPDATE email_verifications SET expires_at=now()-interval '1 second' WHERE owner_id=%s", (account['id'],))
    assert client.post('/api/accounts/verify', json={'token': old}).status_code == 400
    assert client.post('/api/accounts/verify', json={'token': 'wrong-token'}).status_code == 400
    assert client.post('/api/accounts/register', json=body | {'password': 'Another incorrect password'}).status_code == 409
    assert client.post('/api/accounts/register', json=body).status_code == 201
    current = proof(mailbox, body['email'])
    admin = {'Authorization': f"Bearer {environment['admin']['token']}"}  # Component-only role fixture.
    assert client.patch(f"/api/accounts/{account['id']}", json={'disabled': True}, headers=admin).status_code == 200
    assert client.post('/api/accounts/verify', json={'token': current}).status_code == 200
    row = await (await connection.execute('SELECT * FROM accounts WHERE id=%s', (account['id'],))).fetchone()
    assert row['verified'] and row['disabled'] and row['active'] and not row['paid']
    assert client.post('/api/accounts/login', json=body).status_code == 403
    assert client.patch(f"/api/accounts/{account['id']}", json={'disabled': False}, headers=admin).status_code == 200
    assert client.post('/api/accounts/login', json=body).status_code == 200
    assert client.post('/api/accounts/verify', json={'token': old}).status_code == 400


async def test_operator_invitation_roles_admin_boundaries_and_audit(account_client, connection, environment):
    client, mailbox = account_client
    invitation_url = await accounts.bootstrap(connection, 'operator@owned.test')
    invitation = parse_qs(urlsplit(invitation_url).fragment)['invite'][0]
    assert client.post('/api/accounts/register', json=credentials('wrong@owned.test') | {'invitation': invitation}).status_code == 400
    super_account, super_headers = signup(client, mailbox, 'operator@owned.test', invitation)
    assert super_account['role'] == 'super_admin'
    account, user_headers = signup(client, mailbox, 'future-admin@owned.test')
    hashes = await (await connection.execute('SELECT password_hash FROM accounts WHERE email=ANY(%s)', (['operator@owned.test', 'future-admin@owned.test'],))).fetchall()
    assert len({row['password_hash'] for row in hashes}) == 2  # Equal passwords have independent salts.
    assert all(row['password_hash'].startswith('scrypt:131072:8:1:') for row in hashes)
    assert client.patch(f"/api/accounts/{account['id']}", json={'role': 'admin'}, headers=super_headers).status_code == 200
    continued = client.get('/api/accounts/me', headers=user_headers)
    assert continued.status_code == 200 and continued.json()['account']['role'] == 'admin'
    admin_headers = user_headers
    assert client.get('/api/accounts', headers=admin_headers).status_code == 200
    assert client.get(f"/api/conversations/{environment['conversation']}", headers=admin_headers).status_code == 404
    assert client.get('/api/settings', headers=admin_headers).status_code == 403
    assert client.patch('/api/settings', json={'max_active': 6}, headers=admin_headers).status_code == 403
    assert client.get(f"/api/conversations/{environment['conversation']}", headers=super_headers).status_code == 200
    assert client.patch('/api/settings', json={'max_active': 6}, headers=super_headers).status_code == 200
    assert client.patch(f"/api/accounts/{super_account['id']}", json={'disabled': True}, headers=admin_headers).status_code == 403
    assert client.post('/api/accounts/register', json=credentials('another@owned.test') | {'invitation': invitation}).status_code == 400
    audits = await (await connection.execute('SELECT * FROM accounts_audit WHERE target_id=%s ORDER BY id', (account['id'],))).fetchall()
    assert [row['action'] for row in audits] == ['register', 'verify_email', 'update_account']
    assert audits[-1]['previous']['role'] == 'user' and audits[-1]['updated']['role'] == 'admin'
    assert str(audits[-1]['actor_id']) == super_account['id']
    assert 'password' not in str([row['updated'] for row in audits])


def test_concurrent_registration_has_one_account(account_client):
    client, mailbox = account_client
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: client.post('/api/accounts/register', json=credentials('race@owned.test')), range(2)))
    assert all(result.status_code in (201, 409) for result in results)
    assert any(result.status_code == 201 for result in results)
    assert len({result.json()['id'] for result in results if result.status_code == 201}) == 1
    assert client.post('/api/accounts/verify', json={'token': proof(mailbox, 'race@owned.test')}).status_code == 200


def test_resend_links_are_one_use_despite_delivery_order(account_client):
    client, mailbox = account_client
    body = credentials('resend@owned.test')
    assert client.post('/api/accounts/register', json=body).status_code == 201
    first = proof(mailbox, body['email'])
    assert client.post('/api/accounts/register', json=body).status_code == 201
    second = proof(mailbox, body['email'])
    # SMTP completion order can differ from transaction order. Both delivered links
    # remain valid until the first confirmation, which consumes all proofs.
    verified = client.post('/api/accounts/verify', json={'token': first})
    assert verified.status_code == 200
    replay = client.post('/api/accounts/verify', json={'token': first})
    assert replay.status_code == 400
    other = client.post('/api/accounts/verify', json={'token': second})
    assert other.status_code == 400


@pytest.mark.parametrize('changes', [{'disabled': False}, {'role': 'admin'}])
async def test_unchanged_or_increased_access_preserves_session_and_execution(environment, connection, rag_pool, changes):
    token = environment['user']['token']
    request = await answers.admit(connection, token, environment['conversation'], uuid4(), 'owned question',
                                  [environment['document']], environment['tab'], environment['proof'])
    await accounts.mutate(connection, environment['super_admin']['token'], environment['user']['id'], changes)
    current = await (await connection.execute('SELECT * FROM requests WHERE id=%s', (request['id'],))).fetchone()
    assert current['state'] == 'accepted'
    actor = await principal(connection, token)
    assert actor['context_epoch'] == 0
    binding = await (await connection.execute('SELECT * FROM graph_bindings WHERE request_id=%s', (request['id'],))).fetchone()
    async with GuardedSaver(rag_pool, binding).guard():
        pass
    async with Coordinator(rag_pool, 1, None, None).guard(request['id']):
        pass


@pytest.mark.parametrize('mutation', ['logout', 'block', 'soft_delete', 'expiry'])
async def test_origin_session_and_account_mutations_fence_shared_writes(environment, connection, rag_pool, mutation):
    # Existing source/tab projections are component-only; issuer browser proof is separate.
    token, owner = environment['user']['token'], environment['user']['id']
    request = await answers.admit(connection, token, environment['conversation'], uuid4(), 'owned question',
                                  [environment['document']], environment['tab'], environment['proof'])
    assert request['origin_session'] == environment['user']['session_id']
    binding = await (await connection.execute('SELECT * FROM graph_bindings WHERE request_id=%s', (request['id'],))).fetchone()
    saver = GuardedSaver(rag_pool, binding)
    coordinator = Coordinator(rag_pool, 1, None, None)
    async with saver.guard():
        pass
    async with coordinator.guard(request['id']):
        pass
    second_token = 'independent-owned-session'
    await connection.execute("INSERT INTO sessions(token_hash,owner_id,expires_at) VALUES (%s,%s,now()+interval '1 hour')", (secret_hash(second_token), owner))
    if mutation == 'logout':
        await accounts.logout(connection, token)
        assert (await principal(connection, second_token))['id'] == owner
    elif mutation == 'expiry':
        await connection.execute("UPDATE sessions SET expires_at=now()-interval '1 second' WHERE id=%s", (request['origin_session'],))
    else:
        changes = {'disabled': True} if mutation == 'block' else {'active': False}
        await accounts.mutate(connection, environment['admin']['token'], owner, changes)
    with pytest.raises(AccessError):
        async with saver.guard():
            raise AssertionError('invalid session reached saver')
    with pytest.raises(AccessError):
        async with coordinator.guard(request['id']):
            raise AssertionError('invalid session reached native publication')
    if mutation == 'expiry':
        await coordinator.finish(request['id'], 'interrupted', 'session_ended')
    snapshot = await (await connection.execute('SELECT * FROM requests WHERE id=%s', (request['id'],))).fetchone()
    assert snapshot['state'] == 'interrupted'
    terminal = await (await connection.execute("SELECT * FROM events WHERE request_id=%s AND kind='terminal'", (request['id'],))).fetchall()
    assert len(terminal) == 1
    assert await (await connection.execute('SELECT id FROM documents WHERE id=%s', (environment['document'],))).fetchone()
    assert await (await connection.execute('SELECT id FROM messages WHERE request_id=%s', (request['id'],))).fetchone()
    if mutation != 'expiry':
        with pytest.raises(AccessError):
            await answers.admit(connection, token, environment['conversation'], uuid4(), 'late question', [environment['document']], environment['tab'], environment['proof'])


async def test_expired_bootstrap_and_session_are_refused(account_client, connection):
    client, mailbox = account_client
    invitation = parse_qs(urlsplit(await accounts.bootstrap(connection, 'expired@owned.test')).fragment)['invite'][0]
    await connection.execute("UPDATE account_invitations SET expires_at=now()-interval '1 second'")
    assert client.post('/api/accounts/register', json=credentials('expired@owned.test') | {'invitation': invitation}).status_code == 400
    account, headers = signup(client, mailbox, 'expiry@owned.test')
    await connection.execute("UPDATE sessions SET expires_at=now()-interval '1 second' WHERE owner_id=%s", (account['id'],))
    assert client.get('/api/accounts/me', headers=headers).status_code == 401
    assert client.post('/api/accounts/logout', headers=headers).status_code == 200


def test_missing_or_failed_smtp_has_no_verification_bypass(account_client, monkeypatch):
    client, mailbox = account_client
    monkeypatch.delenv('RAG_SMTP_HOST')
    assert client.post('/api/accounts/register', json=credentials()).status_code == 503
    monkeypatch.setenv('RAG_SMTP_HOST', '127.0.0.1')
    monkeypatch.setenv('RAG_SMTP_PORT', str(mailbox.http.server_port))  # HTTP server rejects SMTP greeting.
    result = client.post('/api/accounts/register', json=credentials())
    assert result.status_code == 503 and result.json() == {'error': 'mail_delivery_failed'}
    assert 'token' not in result.text
