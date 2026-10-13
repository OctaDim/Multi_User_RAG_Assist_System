from fastapi import APIRouter, Header, Request

from app import settings
from app.auth import bearer


router = APIRouter(prefix="/api/settings")


@router.get("")
async def read(request: Request, authorization: str | None = Header(None)):
    async with request.app.state.pool.connection() as connection:
        return await settings.read(connection, bearer(authorization))


@router.patch("")
async def write(changes: dict, request: Request, authorization: str | None = Header(None)):
    async with request.app.state.pool.connection() as connection:
        return await settings.write(connection, bearer(authorization), changes)
