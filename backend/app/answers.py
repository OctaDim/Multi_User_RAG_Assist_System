import json
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.auth import AccessError, lock_service, principal, secret_hash


UNFINISHED = ("accepted", "searching", "queued", "generating")


async def conversation(connection, actor, conversation_id, *, read_only=False):
    mode = "SHARE" if read_only else "UPDATE"
    row = await (await connection.execute(f"SELECT * FROM conversations WHERE id=%s FOR {mode}", (conversation_id,))).fetchone()
    if not row or (row["owner_id"] != actor["id"] and not (read_only and actor["role"] == "super_admin")):
        raise AccessError("not_found", 404)
    return row


async def event(connection, request, kind, payload):
    return await (await connection.execute(
        "INSERT INTO events(request_id,conversation_id,kind,payload) VALUES (%s,%s,%s,%s) RETURNING id",
        (request["id"], request["conversation_id"], kind, Jsonb(payload)),
    )).fetchone()


async def admit(connection, token, conversation_id, operation_key, question, document_ids, tab_id, tab_proof):
    scope = sorted(set(document_ids))
    payload = {"conversation": str(conversation_id), "question": question, "documents": list(map(str, scope)), "tab": str(tab_id)}
    fingerprint = secret_hash(json.dumps(payload, sort_keys=True, ensure_ascii=False))
    async with connection.transaction():
        service = await lock_service(connection)
        actor = await principal(connection, token)
        documents = await (await connection.execute(
            "SELECT * FROM documents WHERE id=ANY(%s::uuid[]) AND owner_id=%s ORDER BY id FOR SHARE",
            (scope, actor["id"]),
        )).fetchall()
        history = await conversation(connection, actor, conversation_id)
        tab = await (await connection.execute("SELECT id FROM tabs WHERE id=%s AND owner_id=%s AND proof_hash=%s FOR SHARE", (tab_id, actor["id"], secret_hash(tab_proof)))).fetchone()
        if not tab:
            raise AccessError("invalid_tab")
        previous = await (await connection.execute("SELECT * FROM requests WHERE owner_id=%s AND operation_key=%s", (actor["id"], operation_key))).fetchone()
        if previous:
            if previous["fingerprint"] != fingerprint:
                raise AccessError("operation_conflict", 409)
            return previous
        if await (await connection.execute("SELECT id FROM requests WHERE conversation_id=%s AND state=ANY(%s)", (conversation_id, list(UNFINISHED)))).fetchone():
            raise AccessError("conversation_busy", 409)
        if len(documents) != len(scope):
            raise AccessError("invalid_scope", 404)
        if not any(document["ready"] and not document["deleted"] for document in documents):
            raise AccessError("no_ready_sources", 409)
        if not service["healthy"]:
            raise AccessError("coordinator_unavailable", 503)
        request = await (await connection.execute(
            "INSERT INTO requests(id,conversation_id,owner_id,operation_key,fingerprint,scope,origin_tab,state,execution_epoch,context_epoch) VALUES (%s,%s,%s,%s,%s,%s,%s,'accepted',%s,%s) RETURNING *",
            (uuid4(), conversation_id, actor["id"], operation_key, fingerprint, scope, tab_id, service["epoch"], history["context_epoch"]),
        )).fetchone()
        await connection.execute("INSERT INTO messages(request_id,conversation_id,role,text) VALUES (%s,%s,'user',%s)", (request["id"], conversation_id, question))
        await event(connection, request, "accepted", {"state": "accepted", "version": request["version"]})
        return request


async def transition(connection, request, state, reason):
    updated = await (await connection.execute(
        "UPDATE requests SET state=%s,reason=%s,version=version+1 WHERE id=%s AND state=ANY(%s) RETURNING *",
        (state, reason, request["id"], list(UNFINISHED)),
    )).fetchone()
    if not updated:
        return request
    if state != "completed":
        await connection.execute("UPDATE messages SET excluded=true WHERE request_id=%s AND role='assistant'", (request["id"],))
    await event(connection, updated, "terminal", {"state": state, "reason": reason, "version": updated["version"]})
    return updated


async def stop(connection, token, request_id):
    async with connection.transaction():
        await lock_service(connection)
        actor = await principal(connection, token)
        request = await (await connection.execute("SELECT * FROM requests WHERE id=%s AND owner_id=%s", (request_id, actor["id"]))).fetchone()
        if not request:
            raise AccessError("not_found", 404)
        await conversation(connection, actor, request["conversation_id"])
        request = await (await connection.execute("SELECT * FROM requests WHERE id=%s FOR UPDATE", (request_id,))).fetchone()
        return await transition(connection, request, "interrupted", "user_stop")


async def snapshot(connection, token, conversation_id):
    async with connection.transaction():
        await lock_service(connection)
        actor = await principal(connection, token)
        await conversation(connection, actor, conversation_id, read_only=True)
        messages = await (await connection.execute("SELECT * FROM messages WHERE conversation_id=%s ORDER BY id", (conversation_id,))).fetchall()
        requests = await (await connection.execute("SELECT * FROM requests WHERE conversation_id=%s ORDER BY created_at,id", (conversation_id,))).fetchall()
        watermark = await (await connection.execute("SELECT coalesce(max(id),0) AS watermark FROM events WHERE conversation_id=%s", (conversation_id,))).fetchone()
        return {"conversation_id": conversation_id, "messages": messages, "requests": requests, **watermark}
