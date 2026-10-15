import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Header, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from app import events
from app.auth import AccessError, bearer


router = APIRouter(prefix='/api/tabs')


def encode(value):
    identifier = f"id: {value['id']}\n" if 'id' in value else ''
    return (identifier + f"event: {value['kind']}\ndata: "
            + json.dumps(jsonable_encoder(value), ensure_ascii=False) + '\n\n')


@router.post('')
async def create(request: Request, authorization: str | None = Header(None)):
    async with request.app.state.database.session() as connection:
        return await events.create_tab(connection, bearer(authorization))


@router.post('/{tab_id}/heartbeat')
async def ack(tab_id: UUID, request: Request, authorization: str | None = Header(None),
              tab_proof: str = Header(alias='X-Tab-Proof'),
              epoch: int = Header(alias='X-Connection-Epoch'),
              challenge: str = Header(alias='X-Heartbeat-Challenge')):
    async with request.app.state.database.session() as connection:
        await events.ack(connection, bearer(authorization), tab_id, tab_proof, epoch, challenge)
    return {'confirmed': True}


@router.get('/{tab_id}/events')
async def stream(tab_id: UUID, request: Request, authorization: str | None = Header(None),
                 tab_proof: str = Header(alias='X-Tab-Proof'), last_event_id: int | None = Header(None)):
    token = bearer(authorization)
    database = request.app.state.database
    async with database.session() as connection:
        tab = await events.connect(connection, token, tab_id, tab_proof)
    request.scope.setdefault('state', {})['delivery_epoch'] = tab['connection_epoch']

    async def deliver():
        cursor = last_event_id
        try:
            yield encode({'kind': 'heartbeat', 'payload': tab})
            next_heartbeat = asyncio.get_running_loop().time() + 5
            while True:
                # This DB authorization ends before yielding. U7/U8 must prove the
                # separate transport fence; StreamingResponse alone cannot do so.
                async with database.session() as connection:
                    value = await events.read(connection, token, tab_id, tab_proof, tab['connection_epoch'], cursor)
                if value:
                    yield encode(value)
                    cursor = request.scope['state'].pop('delivery_cursor', value['id'])
                if asyncio.get_running_loop().time() >= next_heartbeat:
                    async with database.session() as connection:
                        heartbeat = await events.heartbeat(connection, token, tab_id, tab_proof, tab['connection_epoch'])
                    if heartbeat:
                        yield encode({'kind': 'heartbeat', 'payload': heartbeat})
                    next_heartbeat = asyncio.get_running_loop().time() + 5
                if not value:
                    await asyncio.sleep(0.1)
        except AccessError:
            return
        finally:
            # Cancellation must leave a durable deadline even if auth was revoked.
            # If the process dies, the shared heartbeat lease supplies detection.
            async def close():
                try:
                    async with database.session() as connection:
                        await events.disconnect(connection, token, tab_id, tab_proof, tab['connection_epoch'])
                except AccessError:
                    pass
            await asyncio.shield(close())

    return StreamingResponse(deliver(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
