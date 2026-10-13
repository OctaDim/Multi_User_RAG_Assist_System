import argparse
import asyncio
from email.message import EmailMessage
import hashlib
import hmac
import os
import re
import secrets
import smtplib
import ssl
from threading import Semaphore
from urllib.parse import urlsplit
from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app import answers
from app.auth import AccessError, lock_service, principal, secret_hash
from app.db import database_url


PUBLIC = ('id', 'email', 'role', 'verified', 'active', 'disabled', 'paid')
# Each OpenSSL scrypt operation uses 128 MiB; serialize KDF work per API process.
KDF_MEMORY = Semaphore(1)


def public(account):
    return {key: account[key] for key in PUBLIC}


def email_address(value):
    value = value.strip().lower()
    if len(value) > 254 or not re.fullmatch(r'[a-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}', value):
        raise AccessError('invalid_email', 422)
    return value


def password_digest(password, salt):
    # OWASP scrypt floor: https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
    with KDF_MEMORY:
        return hashlib.scrypt(password.encode(), salt=salt, n=2**17, r=8, p=1, maxmem=256*1024*1024, dklen=32)


def hash_password(password):
    salt = secrets.token_bytes(16)
    return f'scrypt:131072:8:1:{salt.hex()}:{password_digest(password, salt).hex()}'


def verify_password(password, encoded):
    if not encoded:
        # Missing accounts still pay the same KDF cost; no usable fallback credential.
        password_digest(password, bytes(16))
        return False
    algorithm, n, r, p, salt, digest = encoded.split(':')
    if (algorithm, n, r, p) != ('scrypt', '131072', '8', '1'):
        return False
    return hmac.compare_digest(password_digest(password, bytes.fromhex(salt)), bytes.fromhex(digest))


def frontend_origin():
    origin = os.environ.get('RAG_FRONTEND_ORIGIN', '')
    parsed = urlsplit(origin)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username:
        raise AccessError('frontend_not_configured', 503)
    return origin.rstrip('/')


def mail_configuration():
    host, sender = os.environ.get('RAG_SMTP_HOST'), os.environ.get('RAG_SMTP_FROM')
    security = os.environ.get('RAG_SMTP_SECURITY', 'starttls')
    if not host or not sender or '\n' in sender or '\r' in sender or security not in ('starttls', 'ssl', 'plain'):
        raise AccessError('mail_not_configured', 503)
    if security == 'plain' and host not in ('127.0.0.1', '::1', 'localhost'):
        raise AccessError('mail_tls_required', 503)
    if bool(os.environ.get('RAG_SMTP_USERNAME')) != bool(os.environ.get('RAG_SMTP_PASSWORD')):
        raise AccessError('mail_not_configured', 503)
    try:
        port = int(os.environ.get('RAG_SMTP_PORT', '465' if security == 'ssl' else '587'))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise AccessError('mail_not_configured', 503) from None
    return host, port, sender, security


def deliver_verification(email, token, config, origin):
    host, port, sender, security = config
    message = EmailMessage()
    message['From'], message['To'], message['Subject'] = sender, email, 'Confirm your RAG account'
    # Fragment avoids verification credentials in HTTP request paths/access logs.
    message.set_content(f'Confirm your email address:\n{origin}/#verify={token}\nThis link expires in one hour and can be used once.\n')
    transport = smtplib.SMTP_SSL if security == 'ssl' else smtplib.SMTP
    options = {'context': ssl.create_default_context()} if security == 'ssl' else {}
    with transport(host, port, timeout=10, **options) as smtp:
        if security == 'starttls':
            smtp.starttls(context=ssl.create_default_context())
        username = os.environ.get('RAG_SMTP_USERNAME')
        if username:
            smtp.login(username, os.environ['RAG_SMTP_PASSWORD'])
        smtp.send_message(message)


async def audit(connection, actor_id, target, action, previous):
    await connection.execute(
        'INSERT INTO accounts_audit(actor_id,target_id,action,previous,updated) VALUES (%s,%s,%s,%s,%s)',
        (actor_id, target['id'], action, Jsonb(previous), Jsonb({key: str(value) if key == 'id' else value for key, value in public(target).items()})),
    )


async def register(connection, email, password, invitation=None):
    email = email_address(email)
    config, origin = mail_configuration(), frontend_origin()
    candidate = await (await connection.execute('SELECT * FROM accounts WHERE email=%s', (email,))).fetchone()
    matches = await asyncio.to_thread(verify_password, password, candidate['password_hash']) if candidate else False
    encoded = await asyncio.to_thread(hash_password, password)
    token = secrets.token_urlsafe(32)
    async with connection.transaction():
        await lock_service(connection, exclusive=True)
        previous = await (await connection.execute('SELECT * FROM accounts WHERE email=%s FOR UPDATE', (email,))).fetchone()
        if previous:
            if previous['verified'] or invitation or not matches or previous['password_hash'] != candidate['password_hash']:
                raise AccessError('registration_conflict', 409)
            account = previous
        else:
            role = 'user'
            if invitation:
                row = await (await connection.execute(
                    '''UPDATE account_invitations SET consumed=true WHERE token_hash=%s AND email=%s
                       AND NOT consumed AND expires_at>clock_timestamp() RETURNING role''', (secret_hash(invitation), email),
                )).fetchone()
                if not row:
                    raise AccessError('invalid_invitation', 400)
                role = row['role']
            account = await (await connection.execute(
                'INSERT INTO accounts(id,email,password_hash,role) VALUES (%s,%s,%s,%s) RETURNING *',
                (uuid4(), email, encoded, role),
            )).fetchone()
            await connection.execute('INSERT INTO conversations(id,owner_id) VALUES (%s,%s)', (uuid4(), account['id']))
            from app.documents import initialize_policy
            await initialize_policy(connection, account['id'])
            await audit(connection, None, account, 'bootstrap' if invitation else 'register', {})
        await connection.execute(
            "INSERT INTO email_verifications(token_hash,owner_id,expires_at) VALUES (%s,%s,clock_timestamp()+interval '1 hour')",
            (secret_hash(token), account['id']),
        )
    try:
        await asyncio.to_thread(deliver_verification, email, token, config, origin)
    except (OSError, smtplib.SMTPException):
        # Account stays unverified; repeating registration with its password resends.
        raise AccessError('mail_delivery_failed', 503) from None
    return public(account)


async def verify(connection, token):
    async with connection.transaction():
        await lock_service(connection, exclusive=True)
        candidate = await (await connection.execute('SELECT owner_id FROM email_verifications WHERE token_hash=%s', (secret_hash(token),))).fetchone()
        if not candidate:
            raise AccessError('invalid_verification', 400)
        previous = await (await connection.execute('SELECT * FROM accounts WHERE id=%s FOR UPDATE', (candidate['owner_id'],))).fetchone()
        consumed = await (await connection.execute(
            '''UPDATE email_verifications SET consumed=true WHERE token_hash=%s
               AND NOT consumed AND expires_at>clock_timestamp() RETURNING owner_id''', (secret_hash(token),),
        )).fetchone()
        if not consumed:
            raise AccessError('invalid_verification', 400)
        await connection.execute('UPDATE email_verifications SET consumed=true WHERE owner_id=%s', (previous['id'],))
        account = await (await connection.execute('UPDATE accounts SET verified=true WHERE id=%s RETURNING *', (previous['id'],))).fetchone()
        await audit(connection, account['id'], account, 'verify_email', {key: str(value) if key == 'id' else value for key, value in public(previous).items()})
        return public(account)


async def login(connection, email, password):
    email = email_address(email)
    row = await (await connection.execute('SELECT * FROM accounts WHERE email=%s', (email,))).fetchone()
    if not await asyncio.to_thread(verify_password, password, row['password_hash'] if row else None):
        raise AccessError('invalid_credentials', 401)
    token = secrets.token_urlsafe(32)
    async with connection.transaction():
        await lock_service(connection)
        account = await (await connection.execute('SELECT * FROM accounts WHERE id=%s FOR SHARE', (row['id'],))).fetchone()
        if account['password_hash'] != row['password_hash'] or not account['active'] or account['disabled'] or not account['verified']:
            raise AccessError('access_denied')
        await connection.execute(
            "INSERT INTO sessions(token_hash,owner_id,expires_at) VALUES (%s,%s,clock_timestamp()+interval '12 hours')", (secret_hash(token), account['id']),
        )
    return {'token': token, 'account': public(account)}


async def me(connection, token):
    async with connection.transaction():
        await lock_service(connection)
        actor = await principal(connection, token)
        conversations = await (await connection.execute('SELECT id FROM conversations WHERE owner_id=%s ORDER BY id', (actor['id'],))).fetchall()
        return {'account': public(actor), 'conversations': conversations}


async def terminal_accounts(connection, owner_id, reason, session_id=None):
    affected = await (await connection.execute(
        '''SELECT origin_tab,conversation_id FROM requests WHERE owner_id=%s AND state=ANY(%s)
           AND (%s::uuid IS NULL OR origin_session=%s)''',
        (owner_id, list(answers.UNFINISHED), session_id, session_id),
    )).fetchall()
    tab_ids = sorted({row['origin_tab'] for row in affected})
    conversation_ids = sorted({row['conversation_id'] for row in affected})
    await connection.execute('SELECT id FROM tabs WHERE id=ANY(%s::uuid[]) ORDER BY id FOR UPDATE', (tab_ids,))
    await connection.execute('SELECT id FROM conversations WHERE id=ANY(%s::uuid[]) ORDER BY id FOR UPDATE', (conversation_ids,))
    requests = await (await connection.execute(
        '''SELECT * FROM requests WHERE owner_id=%s AND state=ANY(%s)
           AND (%s::uuid IS NULL OR origin_session=%s) ORDER BY id FOR UPDATE''',
        (owner_id, list(answers.UNFINISHED), session_id, session_id),
    )).fetchall()
    for request in requests:
        await answers.transition(connection, request, 'interrupted', reason)
    if session_id is None:
        await connection.execute('UPDATE tabs SET connected=false,confirmed=false,challenge_hash=NULL WHERE id=ANY(%s::uuid[])', (tab_ids,))


async def logout(connection, token):
    async with connection.transaction():
        await lock_service(connection, exclusive=True)
        row = await (await connection.execute('SELECT owner_id,id FROM sessions WHERE token_hash=%s', (secret_hash(token),))).fetchone()
        if not row:
            raise AccessError('unauthenticated', 401)
        await connection.execute('SELECT id FROM accounts WHERE id=%s FOR UPDATE', (row['owner_id'],))
        # Logout remains available to blocked, expired or already revoked sessions.
        await connection.execute('UPDATE sessions SET revoked=true WHERE id=%s', (row['id'],))
        await terminal_accounts(connection, row['owner_id'], 'logout', row['id'])
    return {'logged_out': True}


async def account_list(connection, token):
    async with connection.transaction():
        await lock_service(connection)
        actor = await principal(connection, token)
        if actor['role'] not in ('admin', 'super_admin'):
            raise AccessError('forbidden')
        return [public(row) for row in await (await connection.execute('SELECT * FROM accounts ORDER BY email,id')).fetchall()]


async def mutate(connection, token, target_id, changes):
    if any(key not in ('role', 'active', 'disabled') for key in changes):
        raise AccessError('invalid_account_changes', 422)
    if ('role' in changes and changes['role'] not in ('user', 'admin', 'super_admin')) or any(type(value) is not bool for key, value in changes.items() if key != 'role'):
        raise AccessError('invalid_account_changes', 422)
    async with connection.transaction():
        await lock_service(connection, exclusive=True)
        identity = await (await connection.execute('SELECT owner_id FROM sessions WHERE token_hash=%s', (secret_hash(token),))).fetchone()
        if not identity:
            raise AccessError('unauthenticated', 401)
        # Take write locks up front, in stable order, before principal's session lock.
        rows = await (await connection.execute('SELECT * FROM accounts WHERE id=ANY(%s::uuid[]) ORDER BY id FOR UPDATE', ([identity['owner_id'], target_id],))).fetchall()
        await connection.execute('SELECT id FROM sessions WHERE owner_id=%s OR token_hash=%s ORDER BY id FOR UPDATE', (target_id, secret_hash(token)))
        actor = await principal(connection, token)
        target = next((row for row in rows if row['id'] == target_id), None)
        if not target:
            raise AccessError('not_found', 404)
        if actor['role'] != 'super_admin' and (actor['role'] != 'admin' or target['role'] != 'user' or 'role' in changes):
            raise AccessError('forbidden')
        if not changes:
            raise AccessError('invalid_account_changes', 422)
        previous = {key: str(value) if key == 'id' else value for key, value in public(target).items()}
        changes = {key: value for key, value in changes.items() if value != target[key]}
        access_lost = (target['verified'] and target['active'] and not target['disabled']
                       and (not changes.get('active', target['active']) or changes.get('disabled', target['disabled'])))
        updated = target
        if changes:
            assignments = ','.join(f'{key}=%s' for key in changes)
            updated = await (await connection.execute(
                f'UPDATE accounts SET {assignments},context_epoch=context_epoch+%s WHERE id=%s RETURNING *', (*changes.values(), int(access_lost), target_id),
            )).fetchone()
        if access_lost:
            await connection.execute('UPDATE sessions SET revoked=true WHERE owner_id=%s', (target_id,))
            await terminal_accounts(connection, target_id, 'account_changed')
            await connection.execute(
                '''UPDATE document_files f SET state='failed',error='document_access_lost',job_id=NULL
                   FROM documents d WHERE d.id=f.document_id AND d.owner_id=%s
                   AND f.state IN ('receiving','queued','processing','awaiting_choice')''', (target_id,),
            )
        await audit(connection, actor['id'], updated, 'update_account', previous)
        return public(updated)


async def bootstrap(connection, email):
    email = email_address(email)
    origin = frontend_origin()
    token = secrets.token_urlsafe(32)
    async with connection.transaction():
        await lock_service(connection, exclusive=True)
        await connection.execute(
            "INSERT INTO account_invitations VALUES (%s,%s,'super_admin',clock_timestamp()+interval '1 hour',false)", (secret_hash(token), email),
        )
    return f'{origin}/#invite={token}'


def main():
    parser = argparse.ArgumentParser(description='Operator-only one-use super-admin invitation; consume through ordinary registration.')
    parser.add_argument('--email', required=True)
    args = parser.parse_args()

    async def run():
        async with await AsyncConnection.connect(database_url(), autocommit=True, row_factory=dict_row) as connection:
            print(await bootstrap(connection, args.email))
    asyncio.run(run())


if __name__ == '__main__':
    main()
