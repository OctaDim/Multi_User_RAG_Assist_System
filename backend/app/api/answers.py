from uuid import UUID

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field

from app import answers
from app.auth import bearer


router = APIRouter(prefix="/api")


class Question(BaseModel):
    operation_key: UUID
    question: str = Field(min_length=1)
    document_ids: list[UUID]
    tab_id: UUID


@router.post('/conversations', status_code=201)
async def create(request: Request, authorization: str | None = Header(None)):
    async with request.app.state.database.session() as connection:
        return await answers.create_conversation(connection, bearer(authorization))


@router.post("/conversations/{conversation_id}/answers")
async def admit(conversation_id: UUID, body: Question, request: Request, authorization: str | None = Header(None), tab_proof: str = Header(alias="X-Tab-Proof")):
    async with request.app.state.database.session() as connection:
        return await answers.admit(connection, bearer(authorization), conversation_id, body.operation_key, body.question, body.document_ids, body.tab_id, tab_proof)


@router.get("/conversations/{conversation_id}")
async def snapshot(conversation_id: UUID, request: Request, authorization: str | None = Header(None)):
    async with request.app.state.database.session() as connection:
        return await answers.snapshot(connection, bearer(authorization), conversation_id)


@router.post("/answers/{request_id}/stop")
async def stop(request_id: UUID, request: Request, authorization: str | None = Header(None)):
    async with request.app.state.database.session() as connection:
        return await answers.stop(connection, bearer(authorization), request_id)
