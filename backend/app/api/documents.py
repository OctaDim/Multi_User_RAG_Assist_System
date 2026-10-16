from uuid import UUID
from typing import Literal
import asyncio
from io import BytesIO

from fastapi import APIRouter, Header, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app import documents
from app.configuration import load_settings
from app.auth import bearer, AccessError


router = APIRouter(prefix='/api/documents')


class UploadFile(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str = Field(min_length=1, max_length=load_settings('policy')['inputs']['filename_max'])
    size: int = Field(gt=0, le=2**63-1)


class UploadBatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    files: list[UploadFile]


class Policy(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    limits: dict[str, int]
    permissions: dict[str, bool]


class ModeChoice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    choice: Literal['complete', 'skip_handwriting', 'cancel']


class PageCorrection(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    page: int = Field(gt=0)
    text: str


class Correction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    base_revision: UUID
    pages: list[PageCorrection]


@router.post('/uploads', status_code=201)
async def admit(body: UploadBatch, request: Request, authorization: str | None = Header(None)):
    async with request.app.state.database.session() as session:
        return await documents.admit_uploads(session, bearer(authorization), [file.model_dump() for file in body.files])


@router.put('/{document_id}/original')
async def upload(document_id: UUID, request: Request, authorization: str | None = Header(None)):
    return await documents.upload(request.app.state.database, bearer(authorization), document_id, request.stream())


@router.get('')
async def listing(request: Request, authorization: str | None = Header(None)):
    async with request.app.state.database.session() as session:
        return await documents.listing(session, bearer(authorization))


@router.get('/policies/{owner_id}')
async def read_policy(owner_id: UUID, request: Request, authorization: str | None = Header(None)):
    async with request.app.state.database.session() as session:
        return await documents.read_policy(session, bearer(authorization), owner_id)


@router.patch('/policies/{owner_id}')
async def update_policy(owner_id: UUID, body: Policy, request: Request, authorization: str | None = Header(None)):
    async with request.app.state.database.session() as session:
        return await documents.update_policy(session, bearer(authorization), owner_id, body.model_dump())


@router.get('/{document_id}')
async def read(document_id: UUID, request: Request, authorization: str | None = Header(None)):
    async with request.app.state.database.session() as session:
        return await documents.read(session, bearer(authorization), document_id)


@router.get('/{document_id}/original')
async def original(document_id: UUID, request: Request, authorization: str | None = Header(None)):
    async with request.app.state.database.session() as session:
        row = await documents.read_original(session, bearer(authorization), document_id)
    # U7 owns reauthorization at the irreversible HTTP handoff, including files.
    return FileResponse(documents.original_path(document_id), filename=row['name'], media_type='application/octet-stream',headers={'Cache-Control':'no-store'})


@router.get('/{document_id}/pages/{page}/original')
async def original_page(document_id: UUID, page: int, request: Request, authorization: str | None = Header(None)):
    from app.ocr import render_pdf_page
    token=bearer(authorization)
    async with request.app.state.database.session() as session:
        row=await documents.read_original(session,token,document_id)
    if row['format']!='pdf':
        raise AccessError('not_found',404)
    image=await asyncio.to_thread(render_pdf_page,documents.original_path(document_id),page)
    output=BytesIO()
    image.save(output,format='PNG')
    async with request.app.state.database.session() as session:
        await documents.read_original(session,token,document_id)
    return Response(output.getvalue(),media_type='image/png',headers={'Cache-Control':'no-store'})


@router.get('/admin/{owner_id}/library')
async def admin_listing(owner_id: UUID, request: Request, authorization: str | None = Header(None)):
    async with request.app.state.database.session() as session:
        return await documents.listing(session, bearer(authorization), owner_id)


@router.post('/{document_id}/mode')
async def choose(document_id: UUID, body: ModeChoice, request: Request, authorization: str | None = Header(None)):
    async with request.app.state.database.session() as session:
        return await documents.choose_mode(session, bearer(authorization), document_id, body.choice)


@router.post('/{document_id}/corrections')
async def correct(document_id: UUID, body: Correction, request: Request, authorization: str | None = Header(None)):
    async with request.app.state.database.session() as session:
        return await documents.correct(session, bearer(authorization), document_id, body.base_revision, [page.model_dump() for page in body.pages])


@router.delete('/{document_id}')
async def delete(document_id: UUID, request: Request, authorization: str | None = Header(None)):
    async with request.app.state.database.session() as session:
        return await documents.delete(session, bearer(authorization), document_id)
