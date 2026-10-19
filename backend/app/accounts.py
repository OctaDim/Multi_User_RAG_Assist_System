import argparse
import asyncio
from datetime import timedelta
from email.message import EmailMessage
import hashlib
import hmac
import os
import re
import secrets
import smtplib
import ssl
from threading import Semaphore
from functools import lru_cache
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import func, insert, or_, select, update

from app import answers
from app.auth import AccessError, lock_service, principal, secret_hash
from app.db import Database, database_url, migrate
from app.configuration import load_service_config, load_settings
from app.models import (Account, AccountInvitation, AccountsAudit, Conversation, Document,
                        DocumentFile, EmailVerification, Request, Session, Tab)


PUBLIC = ('id', 'email', 'role', 'verified', 'active', 'disabled', 'paid')
@lru_cache(maxsize=1)
def kdf_memory():
    return Semaphore(load_settings('policy')['security']['kdf_concurrency'])


def password_profile():
    config = load_settings('policy')['security']
    return dict(n=config['scrypt_n'], r=config['scrypt_r'], p=config['scrypt_p'],
                dklen=config['scrypt_dklen'], salt_bytes=config['salt_bytes'])


def public(account):
    return {key: account[key] for key in PUBLIC}


def email_address(value):
    value = value.strip().lower()
    limits = load_settings('policy')['inputs']
    if not limits['email_min'] <= len(value) <= limits['email_max'] or not re.fullmatch(r'[a-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}', value):
        raise AccessError('invalid_email', 422)
    return value


def password_digest(password, salt, profile=None):
    profile = profile or password_profile()
    with kdf_memory():
        return hashlib.scrypt(password.encode(), salt=salt, n=profile['n'], r=profile['r'], p=profile['p'],
                              maxmem=load_settings('policy')['security']['scrypt_maxmem'], dklen=profile['dklen'])


def hash_password(password):
    profile = password_profile()
    salt = secrets.token_bytes(profile['salt_bytes'])
    return f"scrypt:{profile['n']}:{profile['r']}:{profile['p']}:{salt.hex()}:{password_digest(password, salt, profile).hex()}"


def verify_password(password, encoded):
    profile = password_profile()
    if not encoded:
        # Missing accounts pay the active KDF cost, without a fallback credential.
        password_digest(password, bytes(profile['salt_bytes']), profile)
        return False
    try:
        algorithm, n, r, p, salt, digest = encoded.split(':')
        salt, digest = bytes.fromhex(salt), bytes.fromhex(digest)
        saved = dict(n=int(n), r=int(r), p=int(p), dklen=len(digest), salt_bytes=len(salt))
    except (ValueError, TypeError):
        return False
    allowed = [profile] + load_settings('policy')['security']['legacy_scrypt']
    if algorithm != 'scrypt' or saved not in allowed:
        return False
    return hmac.compare_digest(password_digest(password, salt, saved), digest)


def validate_credentials(password):
    limits = load_settings('policy')['inputs']
    if not limits['password_min'] <= len(password) <= limits['password_max']:
        raise AccessError('invalid_input', 422)


def expiry_description(seconds):
    if seconds == 3600:
        return 'one hour'
    return f'{seconds:g} seconds'


def frontend_origin():
    origin = os.environ.get('RAG_FRONTEND_ORIGIN', '')
    parsed = urlsplit(origin)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username:
        raise AccessError('frontend_not_configured', 503)
    return origin.rstrip('/')


def mail_configuration():
    defaults = load_service_config()['smtp']
    host, sender = os.environ.get('RAG_SMTP_HOST'), os.environ.get('RAG_SMTP_FROM')
    security = os.environ.get('RAG_SMTP_SECURITY', defaults['security'])
    if not host or not sender or '\n' in sender or '\r' in sender or security not in ('starttls', 'ssl', 'plain'):
        raise AccessError('mail_not_configured', 503)
    if security == 'plain' and host not in ('127.0.0.1', '::1', 'localhost'):
        raise AccessError('mail_tls_required', 503)
    if bool(os.environ.get('RAG_SMTP_USERNAME')) != bool(os.environ.get('RAG_SMTP_PASSWORD')):
        raise AccessError('mail_not_configured', 503)
    try:
        port = int(os.environ.get('RAG_SMTP_PORT', str(defaults['ports'][security])))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        raise AccessError('mail_not_configured', 503) from None
    return host, port, sender, security


def deliver_verification(email, token, config, origin):
    host, port, sender, security = config
    message = EmailMessage()
    policy = load_settings('policy')
    message['From'], message['To'], message['Subject'] = sender, email, policy['mail']['subject']
    # Fragment avoids verification credentials in HTTP request paths/access logs.
    message.set_content(policy['mail']['verification_template'].format(
        origin=origin, token=token, expiry=expiry_description(policy['accounts']['verification_seconds'])))
    transport = smtplib.SMTP_SSL if security == 'ssl' else smtplib.SMTP
    options = {'context': ssl.create_default_context()} if security == 'ssl' else {}
    timeout = float(os.environ.get('RAG_SMTP_TIMEOUT', load_service_config()['smtp']['timeout_seconds']))
    with transport(host, port, timeout=timeout, **options) as smtp:
        if security == 'starttls':
            smtp.starttls(context=ssl.create_default_context())
        username = os.environ.get('RAG_SMTP_USERNAME')
        if username:
            smtp.login(username, os.environ['RAG_SMTP_PASSWORD'])
        smtp.send_message(message)


async def audit(session, actor_id, target, action, previous):
    await session.execute(insert(AccountsAudit.__table__).values(
        actor_id=actor_id, target_id=target['id'], action=action, previous=previous,
        updated={key: str(value) if key == 'id' else value for key, value in public(target).items()},
    ))


async def register(session, email, password, invitation=None):
    email = email_address(email)
    validate_credentials(password)
    config, origin = mail_configuration(), frontend_origin()
    async with session.begin():
        candidate = (await session.execute(select(Account.__table__).where(Account.email == email))).mappings().first()
        candidate = dict(candidate) if candidate else None
    matches = await asyncio.to_thread(verify_password, password, candidate['password_hash']) if candidate else False
    encoded = await asyncio.to_thread(hash_password, password)
    token = secrets.token_urlsafe(load_settings('policy')['security']['token_bytes'])
    async with session.begin():
        await lock_service(session, exclusive=True)
        previous = (await session.execute(
            select(Account.__table__).where(Account.email == email).with_for_update()
        )).mappings().first()
        if previous:
            if previous['verified'] or invitation or not matches or previous['password_hash'] != candidate['password_hash']:
                raise AccessError('registration_conflict', 409)
            account = dict(previous)
        else:
            role = 'user'
            if invitation:
                row = (await session.execute(
                    update(AccountInvitation.__table__)
                    .where(AccountInvitation.token_hash == secret_hash(invitation), AccountInvitation.email == email,
                           ~AccountInvitation.consumed, AccountInvitation.expires_at > func.clock_timestamp())
                    .values(consumed=True).returning(AccountInvitation.role)
                )).mappings().first()
                if not row:
                    raise AccessError('invalid_invitation', 400)
                role = row['role']
            account = dict((await session.execute(
                insert(Account.__table__).values(id=uuid4(), email=email, password_hash=encoded, role=role)
                .returning(Account.__table__)
            )).mappings().one())
            from app.documents import initialize_policy
            await initialize_policy(session, account['id'])
            await audit(session, None, account, 'bootstrap' if invitation else 'register', {})
        await session.execute(insert(EmailVerification.__table__).values(
            token_hash=secret_hash(token), owner_id=account['id'],
            expires_at=func.clock_timestamp() + timedelta(seconds=load_settings('policy')['accounts']['verification_seconds']),
        ))
    try:
        await asyncio.to_thread(deliver_verification, email, token, config, origin)
    except (OSError, smtplib.SMTPException):
        # Account stays unverified; repeating registration with its password resends.
        raise AccessError('mail_delivery_failed', 503) from None
    return public(account)


async def verify(session, token):
    async with session.begin():
        await lock_service(session, exclusive=True)
        candidate = (await session.execute(
            select(EmailVerification.owner_id).where(EmailVerification.token_hash == secret_hash(token))
        )).mappings().first()
        if not candidate:
            raise AccessError('invalid_verification', 400)
        previous = (await session.execute(
            select(Account.__table__).where(Account.id == candidate['owner_id']).with_for_update()
        )).mappings().one()
        consumed = (await session.execute(
            update(EmailVerification.__table__)
            .where(EmailVerification.token_hash == secret_hash(token), ~EmailVerification.consumed,
                   EmailVerification.expires_at > func.clock_timestamp())
            .values(consumed=True).returning(EmailVerification.owner_id)
        )).mappings().first()
        if not consumed:
            raise AccessError('invalid_verification', 400)
        await session.execute(update(EmailVerification.__table__).where(
            EmailVerification.owner_id == previous['id']).values(consumed=True))
        account = dict((await session.execute(
            update(Account.__table__).where(Account.id == previous['id']).values(verified=True)
            .returning(Account.__table__)
        )).mappings().one())
        await audit(session, account['id'], account, 'verify_email', {key: str(value) if key == 'id' else value for key, value in public(previous).items()})
        return public(account)


async def login(session, email, password):
    email = email_address(email)
    validate_credentials(password)
    async with session.begin():
        row = (await session.execute(select(Account.__table__).where(Account.email == email))).mappings().first()
        row = dict(row) if row else None
    if not await asyncio.to_thread(verify_password, password, row['password_hash'] if row else None):
        raise AccessError('invalid_credentials', 401)
    token = secrets.token_urlsafe(load_settings('policy')['security']['token_bytes'])
    async with session.begin():
        await lock_service(session)
        account = (await session.execute(
            select(Account.__table__).where(Account.id == row['id']).with_for_update(read=True)
        )).mappings().one()
        if account['password_hash'] != row['password_hash'] or not account['active'] or account['disabled'] or not account['verified']:
            raise AccessError('access_denied')
        await session.execute(insert(Session.__table__).values(
            token_hash=secret_hash(token), owner_id=account['id'],
            expires_at=func.clock_timestamp() + timedelta(seconds=load_settings('policy')['accounts']['session_seconds']),
        ))
    return {'token': token, 'account': public(account)}


async def me_view(session, actor):
    conversations = (await session.execute(
        select(Conversation.id).where(Conversation.owner_id == actor['id']).order_by(Conversation.id)
    )).mappings().all()
    return {'account': public(actor), 'conversations': [dict(row) for row in conversations]}


async def me(session, token):
    async with session.begin():
        await lock_service(session)
        actor = await principal(session, token)
        return await me_view(session, actor)


async def terminal_accounts(session, owner_id, reason, session_id=None):
    filters = [Request.owner_id == owner_id, Request.state.in_(answers.UNFINISHED)]
    if session_id is not None:
        filters.append(Request.origin_session == session_id)
    affected = (await session.execute(
        select(Request.origin_tab, Request.conversation_id).where(*filters)
    )).mappings().all()
    tab_ids = sorted({row['origin_tab'] for row in affected})
    conversation_ids = sorted({row['conversation_id'] for row in affected})
    await session.execute(select(Tab.id).where(Tab.id.in_(tab_ids)).order_by(Tab.id).with_for_update())
    await session.execute(select(Conversation.id).where(Conversation.id.in_(conversation_ids))
                          .order_by(Conversation.id).with_for_update())
    requests = (await session.execute(
        select(Request.__table__).where(*filters).order_by(Request.id).with_for_update()
    )).mappings().all()
    for request in requests:
        await answers.transition(session, dict(request), 'interrupted', reason)
    if session_id is None:
        await session.execute(update(Tab.__table__).where(Tab.id.in_(tab_ids))
                              .values(connected=False, confirmed=False, challenge_hash=None))


async def logout(session, token):
    async with session.begin():
        await lock_service(session, exclusive=True)
        row = (await session.execute(
            select(Session.owner_id, Session.id).where(Session.token_hash == secret_hash(token))
        )).mappings().first()
        if not row:
            raise AccessError('unauthenticated', 401)
        await session.execute(select(Account.id).where(Account.id == row['owner_id']).with_for_update())
        # Logout remains available to blocked, expired or already revoked sessions.
        await session.execute(update(Session.__table__).where(Session.id == row['id']).values(revoked=True))
        await terminal_accounts(session, row['owner_id'], 'logout', row['id'])
    return {'logged_out': True}


async def account_list_view(session, actor):
    if actor['role'] not in ('admin', 'super_admin'):
        raise AccessError('forbidden')
    rows = (await session.execute(select(Account.__table__).order_by(Account.email, Account.id))).mappings().all()
    return [public(row) for row in rows]


async def account_list(session, token):
    async with session.begin():
        await lock_service(session)
        actor = await principal(session, token)
        return await account_list_view(session, actor)


async def mutate(session, token, target_id, changes):
    if any(key not in ('role', 'active', 'disabled') for key in changes):
        raise AccessError('invalid_account_changes', 422)
    if ('role' in changes and changes['role'] not in ('user', 'admin', 'super_admin')) or any(type(value) is not bool for key, value in changes.items() if key != 'role'):
        raise AccessError('invalid_account_changes', 422)
    async with session.begin():
        await lock_service(session, exclusive=True)
        identity = (await session.execute(
            select(Session.owner_id).where(Session.token_hash == secret_hash(token))
        )).mappings().first()
        if not identity:
            raise AccessError('unauthenticated', 401)
        # Take write locks up front, in stable order, before principal's session lock.
        rows = (await session.execute(
            select(Account.__table__).where(Account.id.in_([identity['owner_id'], target_id]))
            .order_by(Account.id).with_for_update()
        )).mappings().all()
        await session.execute(select(Session.id).where(or_(Session.owner_id == target_id,
            Session.token_hash == secret_hash(token))).order_by(Session.id).with_for_update())
        actor = await principal(session, token)
        target = next((dict(row) for row in rows if row['id'] == target_id), None)
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
            updated = dict((await session.execute(
                update(Account.__table__).where(Account.id == target_id)
                .values(**changes, context_epoch=Account.context_epoch + int(access_lost))
                .returning(Account.__table__)
            )).mappings().one())
        if access_lost:
            await session.execute(update(Session.__table__).where(Session.owner_id == target_id).values(revoked=True))
            await terminal_accounts(session, target_id, 'account_changed')
            await session.execute(update(DocumentFile.__table__)
                .where(Document.id == DocumentFile.document_id, Document.owner_id == target_id,
                       DocumentFile.state.in_(('receiving', 'queued', 'processing', 'awaiting_choice')))
                .values(state='failed', error='document_access_lost', job_id=None))
        await audit(session, actor['id'], updated, 'update_account', previous)
        return public(updated)


async def bootstrap(session, email):
    email = email_address(email)
    origin = frontend_origin()
    token = secrets.token_urlsafe(load_settings('policy')['security']['token_bytes'])
    async with session.begin():
        await lock_service(session, exclusive=True)
        await session.execute(insert(AccountInvitation.__table__).values(
            token_hash=secret_hash(token), email=email, role='super_admin',
            expires_at=func.clock_timestamp() + timedelta(seconds=load_settings('policy')['accounts']['invitation_seconds']), consumed=False,
        ))
    return f'{origin}/#invite={token}'


def main():
    parser = argparse.ArgumentParser(description='Operator-only one-use super-admin invitation; consume through ordinary registration.')
    parser.add_argument('--email', required=True)
    args = parser.parse_args()

    async def run():
        dsn = database_url()
        database = Database(dsn)
        try:
            await migrate(dsn)
            async with database.session() as session:
                print(await bootstrap(session, args.email))
        finally:
            await database.dispose()
    asyncio.run(run())


if __name__ == '__main__':
    main()
