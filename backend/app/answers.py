import asyncio
import json
import os
from uuid import uuid4

from sqlalchemy import func, insert, select, update

from app.models import Conversation, Document, Event, GraphBinding, Message, Request

from app.auth import AccessError, lock_service, principal, secret_hash
from app.sources import available, ready_document_ids, source_flags, source_flags_for, cited_spans


UNFINISHED = ("accepted", "searching", "queued", "generating")


async def project(connection, request, *, flags=None):
    if flags is None:
        flags = await source_flags(connection, request['id'])
    return {**request, 'citations': cited_spans(request['answer_text'], request['passport']),
            'source_flags': flags, 'excluded': bool(flags) or request['state'] in ('interrupted', 'failed')}


def question_budget(question, generation=None):
    from app.llama_runtime import Vocabulary
    from app.rag import pack_context
    path = os.environ.get('RAG_MODEL_PATH')
    if not path:
        raise AccessError('tokenizer_unavailable', 503)
    vocabulary = Vocabulary(path)
    try:
        pack_context(question, [], [], vocabulary.tokenize,
                     n_ctx=generation['n_ctx'] if generation is not None else None)
    finally:
        vocabulary.close()


async def create_conversation(connection, token):
    async with connection.begin():
        await lock_service(connection)
        actor = await principal(connection, token)
        return dict((await connection.execute(insert(Conversation.__table__).values(id=uuid4(), owner_id=actor["id"]).returning(Conversation.id))).mappings().first())


async def conversation(connection, actor, conversation_id, *, read_only=False):
    row = (await connection.execute(select(Conversation.__table__).where(Conversation.id == conversation_id).with_for_update(read=read_only))).mappings().first()
    if not row or (row["owner_id"] != actor["id"] and not (read_only and actor["role"] == "super_admin")):
        raise AccessError("not_found", 404)
    return dict(row)


async def event(connection, request, kind, payload):
    return dict((await connection.execute(insert(Event.__table__).values(request_id=request["id"], conversation_id=request["conversation_id"], kind=kind, payload=payload).returning(Event.id))).mappings().first())


async def admit(connection, token, conversation_id, operation_key, question, document_ids, tab_id, tab_proof):
    selected = sorted(set(document_ids))
    payload = {"conversation": str(conversation_id), "question": question, "documents": list(map(str, selected)), "tab": str(tab_id)}
    fingerprint = secret_hash(json.dumps(payload, sort_keys=True, ensure_ascii=False))
    passport = {'scope_mode': 'selected' if selected else 'all',
                'selected_document_ids': list(map(str, selected))}
    # Authenticate before expensive tokenization, then release all mutation locks.
    # The full admission transaction below rechecks everything before INSERT.
    async with connection.begin():
        await lock_service(connection)
        actor = await principal(connection, token)
        await conversation(connection, actor, conversation_id)
        previous = (await connection.execute(select(Request.__table__).where(Request.owner_id == actor["id"], Request.operation_key == operation_key))).mappings().first()
        if previous:
            if previous['fingerprint'] != fingerprint:
                raise AccessError('operation_conflict', 409)
            return await project(connection, previous)
        from app import settings
        generation = (await settings.current(connection))['values']
    await asyncio.to_thread(question_budget, question, generation)
    async with connection.begin():
        service = await lock_service(connection)
        actor = await principal(connection, token)
        scope = selected if selected else await ready_document_ids(connection, actor['id'])
        documents = (await connection.execute(select(Document.__table__).where(Document.id.in_(scope), Document.owner_id == actor["id"]).order_by(Document.id).with_for_update(read=True))).mappings().all()
        from app.events import live, lock_tab
        tab = await lock_tab(connection, actor, tab_id, tab_proof)
        history = await conversation(connection, actor, conversation_id)
        previous = (await connection.execute(select(Request.__table__).where(Request.owner_id == actor["id"], Request.operation_key == operation_key))).mappings().first()
        if previous:
            if previous["fingerprint"] != fingerprint:
                raise AccessError("operation_conflict", 409)
            return await project(connection, previous)
        if not live(tab):
            raise AccessError("tab_disconnected", 409)
        if (await connection.execute(select(Request.id).where(Request.conversation_id == conversation_id, Request.state.in_(UNFINISHED)))).mappings().first():
            raise AccessError("conversation_busy", 409)
        if len(documents) != len(scope):
            raise AccessError("invalid_scope", 404)
        if not await available(connection, actor["id"], scope):
            raise AccessError("no_ready_sources", 409)
        if not service["healthy"]:
            raise AccessError("coordinator_unavailable", 503)
        request = (await connection.execute(insert(Request.__table__).values(id=uuid4(), conversation_id=conversation_id, owner_id=actor["id"], operation_key=operation_key, fingerprint=fingerprint, scope=scope, passport=passport, origin_tab=tab_id, origin_session=actor["session_id"], state="accepted", execution_epoch=service["epoch"], context_epoch=history["context_epoch"]).returning(Request.__table__))).mappings().first()
        await connection.execute(insert(GraphBinding.__table__).values(request_id=request["id"], thread_id=f"{conversation_id}:{request['id']}:{history['context_epoch']}", owner_id=actor["id"], conversation_id=conversation_id, execution_epoch=service["epoch"], context_epoch=history["context_epoch"], account_epoch=actor["context_epoch"]))
        await connection.execute(insert(Message.__table__).values(request_id=request["id"], conversation_id=conversation_id, role="user", text=question))
        await event(connection, request, "accepted", {
            "state": "accepted", "version": request["version"], "question": question,
            "operation_key": str(operation_key), "scope": list(map(str, scope)),
            "passport": passport, **passport,
            "created_at": request['created_at'].isoformat(),
        })
        return await project(connection, request)


async def transition(connection, request, state, reason):
    updated = (await connection.execute(update(Request.__table__).where(Request.id == request["id"], Request.state.in_(UNFINISHED)).values(state=state, reason=reason, version=Request.version + 1).returning(Request.__table__))).mappings().first()
    if not updated:
        return dict(request)
    if state != "completed":
        await connection.execute(update(Message.__table__).where(Message.request_id == request["id"], Message.role == "assistant").values(excluded=True))
    flags = await source_flags(connection, request['id'])
    if flags:
        await connection.execute(update(Message.__table__).where(Message.request_id == request["id"], Message.role == "assistant").values(excluded=True, source_flags=flags))
    await event(connection, updated, "terminal", {"state": state, "reason": reason, "version": updated["version"],
                                                'source_flags': flags, 'excluded': bool(flags) or state != 'completed'})
    return dict(updated)


async def stop(connection, token, request_id):
    async with connection.begin():
        await lock_service(connection)
        actor = await principal(connection, token)
        request = (await connection.execute(select(Request.__table__).where(Request.id == request_id, Request.owner_id == actor["id"]))).mappings().first()
        if not request:
            raise AccessError("not_found", 404)
        await conversation(connection, actor, request["conversation_id"])
        request = (await connection.execute(select(Request.__table__).where(Request.id == request_id).with_for_update())).mappings().first()
        return await transition(connection, request, "interrupted", "user_stop")


async def histories(connection, conversation_ids):
    result = {identifier: {"conversation_id": identifier, "messages": [], "requests": [], "watermark": 0}
              for identifier in conversation_ids}
    messages = (await connection.execute(select(Message.__table__).where(Message.conversation_id.in_(conversation_ids)).order_by(Message.id))).mappings().all()
    requests = (await connection.execute(select(Request.__table__).where(Request.conversation_id.in_(conversation_ids)).order_by(Request.created_at, Request.id))).mappings().all()
    watermarks = (await connection.execute(select(Event.conversation_id, func.max(Event.id).label("watermark")).where(Event.conversation_id.in_(conversation_ids)).group_by(Event.conversation_id))).mappings().all()
    flags = await source_flags_for(connection, [request['id'] for request in requests])
    for message in messages:
        result[message["conversation_id"]]["messages"].append(dict(message))
    for request in requests:
        result[request["conversation_id"]]["requests"].append(await project(connection, request, flags=flags.get(request['id'], {})))
    for watermark in watermarks:
        result[watermark["conversation_id"]]["watermark"] = watermark["watermark"]
    return list(result.values())


async def snapshot(connection, token, conversation_id):
    async with connection.begin():
        await lock_service(connection, exclusive=True)
        actor = await principal(connection, token)
        return await snapshot_view(connection, actor, conversation_id)


async def snapshot_view(connection, actor, conversation_id):
    await conversation(connection, actor, conversation_id, read_only=True)
    return (await histories(connection, [conversation_id]))[0]
