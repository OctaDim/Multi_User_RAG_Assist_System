"""Private delivery on the pinned H11 transport, after network backpressure.

The service row serializes this synchronous transport write with all mutations.
No database transaction remains open while waiting for network drainage.
"""
import json
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from uvicorn.protocols.http.h11_impl import H11Protocol
from sqlalchemy import select

from app.auth import AccessError, lock_service, principal
from app.models import Account, Request


def json_bytes(value):
    return json.dumps(jsonable_encoder(value), ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


async def view(session, scope, token, actor, value=None):
    """Authorize the response's resource and rebuild current read projections."""
    from app import accounts, answers, documents, events, settings
    endpoint = scope.get('endpoint')
    module, name = getattr(endpoint, '__module__', ''), getattr(endpoint, '__name__', '')
    params = {key: UUID(value) if key.endswith('_id') and isinstance(value, str) else value
              for key, value in scope.get('path_params', {}).items()}
    if module == 'app.api.accounts':
        if name == 'me':
            return await accounts.me_view(session, actor)
        if name == 'account_list':
            return await accounts.account_list_view(session, actor)
        if name == 'login':
            return {'token': token, 'account': accounts.public(actor)}
        if name == 'mutate':
            target = (await session.execute(
                select(Account.__table__).where(Account.id == params['target_id']).with_for_update(read=True)
            )).mappings().first()
            if not target or (target['id'] != actor['id'] and actor['role'] != 'super_admin'
                              and not (actor['role'] == 'admin' and target['role'] == 'user')):
                raise AccessError('forbidden')
            return accounts.public(target)
    elif module == 'app.api.settings':
        await settings.require_super_admin(session, token)
        return await settings.current(session)
    elif module == 'app.api.documents':
        if name in ('listing', 'admin_listing'):
            return await documents.listing_view(session, actor, params.get('owner_id'))
        if name in ('read_policy', 'update_policy'):
            if name == 'update_policy' and actor['role'] not in ('admin', 'super_admin'):
                raise AccessError('forbidden')
            return await documents.read_policy_view(session, actor, params['owner_id'])
        if name == 'read':
            return await documents.read_view(session, actor, params['document_id'])
        if name in ('original', 'original_page'):
            await documents.read_original_view(session, actor, params['document_id'])
        elif name in ('upload', 'choose', 'correct'):
            current = await documents.owned(session, actor, params['document_id'], write=True)
            if value is not None:
                # Preserve command-specific ACK fields while refreshing stored fields.
                return {**value, **{key: current[key] for key in value.keys() & current.keys()}}
        elif name == 'admit' and value is not None:
            for document in value['documents']:
                current = await documents.owned(session, actor, document['id'], write=True)
                document.update({key: current[key] for key in document.keys() & current.keys()})
    elif module == 'app.api.answers':
        if name == 'snapshot':
            return await answers.snapshot_view(session, actor, params['conversation_id'])
        if name in ('admit', 'stop') and value is not None:
            current = (await session.execute(
                select(Request.__table__).where(Request.id == value['id'], Request.owner_id == actor['id'])
                .with_for_update(read=True)
            )).mappings().first()
            if not current:
                raise AccessError('not_found', 404)
            await answers.conversation(session, actor, current['conversation_id'], read_only=True)
            return await answers.project(session, dict(current))
        if name == 'create' and value is not None:
            await answers.conversation(session, actor, value['id'], read_only=True)
    elif module == 'app.api.tabs':
        if name == 'stream':
            headers = dict(scope['headers'])
            tab = await events.delivery_tab(session, token, params['tab_id'], headers[b'x-tab-proof'].decode('latin1'), scope['state']['delivery_epoch'])
            scope['state']['delivery_until'] = min(tab['ack_until'], tab['deadline'] or tab['ack_until'])
        elif name == 'create' and value is not None:
            await events.lock_tab(session, actor, value['id'], value['proof'])
        elif name == 'ack':
            headers = dict(scope['headers'])
            await events.delivery_tab(session, token, params['tab_id'], headers[b'x-tab-proof'].decode('latin1'), int(headers[b'x-connection-epoch']))
    return value


async def serialize(session, grant, message):
    scope, token, media = grant
    body = message.get('body', b'')
    value = json.loads(body) if body and media == 'application/json' else None
    if getattr(scope.get('endpoint'), '__module__', '') == 'app.api.accounts' and getattr(scope.get('endpoint'), '__name__', '') == 'login':
        if value is None:
            return message  # Headers carry no login credential.
        token = value['token']
    actor = await principal(session, token)
    value = await view(session, scope, token, actor, value)
    message = {**message, 'rag.expires_at':actor['session_expires_at']}
    if body and media == 'application/json':
        return {**message, 'body': json_bytes(value)}
    if body and media == 'text/event-stream':
        from app import events
        from app.api.tabs import encode
        prepared = json.loads(body.decode().split('data: ', 1)[1])
        current = await events.delivery_event(session, actor, prepared)
        return {**message, 'body': encode(current).encode(), 'rag.cursor':current.get('id')}
    return message


class GuardedH11Protocol(H11Protocol):
    def handle_events(self):
        previous = self.cycle
        super().handle_events()
        if self.cycle is None or self.cycle is previous:
            return
        cycle = self.cycle
        cycle.scope.setdefault('extensions', {})['rag.handoff'] = True
        original = cycle.send

        async def guarded(message):
            grant = message.get('rag.grant')
            if grant is None:
                await original(message)
                return
            scope = grant[0]
            database = scope['app'].state.database
            while not cycle.disconnected:
                if cycle.flow.write_paused:
                    await cycle.flow.drain()
                try:
                    async with database.session() as session, session.begin():
                        await lock_service(session, exclusive=True)
                        current = await serialize(session, grant, message)
                        if cycle.flow.write_paused:
                            continue
                        from app.events import now
                        current_time = now()
                        # Clock expiry cannot be held by a row lock. Check it
                        # synchronously after serialization, before any byte write.
                        if current.get('rag.expires_at') is not None and current_time >= current['rag.expires_at']:
                            raise AccessError('unauthenticated', 401)
                        until = scope.get('state', {}).get('delivery_until')
                        if until is not None and current_time >= until:
                            raise AccessError('tab_disconnected', 409)
                        # Pinned cycle.send has no await after this ready-flow check.
                        await original(current)
                        if current.get('rag.cursor') is not None:
                            scope['state']['delivery_cursor'] = current['rag.cursor']
                        return
                except AccessError as error:
                    if not cycle.response_started:
                        await original({'type':'http.response.start', 'status':error.status,
                                        'headers':[(b'content-type', b'application/json')]})
                        await original({'type':'http.response.body', 'body':json_bytes({'error':error.code})})
                    else:
                        cycle.transport.close()
                    cycle.disconnected = True
                    return

        cycle.send = guarded


class HandoffMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        authorization = dict(scope.get('headers', [])).get(b'authorization', b'')
        token = authorization[7:].decode('latin1') if authorization.startswith(b'Bearer ') else None
        login = scope['path'] == '/api/accounts/login' and scope['method'] == 'POST'
        protected = (token is not None and scope['path'] != '/api/accounts/logout') or login
        if protected and not scope.get('extensions', {}).get('rag.handoff'):
            await JSONResponse({'error':'protected_transport_unavailable'}, status_code=503)(scope, receive, send)
            return
        private, media = False, ''

        async def checked(message):
            nonlocal private, media
            if message['type'] == 'http.response.start':
                private = protected and message['status'] < 400
                media = dict(message.get('headers', [])).get(b'content-type', b'').decode().split(';')[0]
                if private and media == 'application/json':
                    # Current projections can differ in length from prepared JSON.
                    message = {**message, 'headers':[(key,value) for key,value in message.get('headers',[]) if key != b'content-length']}
            if private:
                message = {**message, 'rag.grant': (scope, token, media)}
            await send(message)

        await self.app(scope, receive, checked)
