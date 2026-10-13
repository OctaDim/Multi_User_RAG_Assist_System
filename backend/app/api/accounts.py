from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, ConfigDict, Field

from app import accounts
from app.auth import bearer


router = APIRouter(prefix='/api/accounts')


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=15, max_length=1024)


class Registration(Credentials):
    invitation: str | None = Field(default=None, min_length=1, max_length=128)


class Verification(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: str = Field(min_length=1, max_length=128)


class AccountChanges(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    role: Literal['user', 'admin', 'super_admin'] | None = None
    active: bool | None = None
    disabled: bool | None = None


@router.post('/register', status_code=201)
async def register(body: Registration, request: Request):
    async with request.app.state.pool.connection() as connection:
        return await accounts.register(connection, body.email, body.password, body.invitation)


@router.post('/verify')
async def verify(body: Verification, request: Request):
    async with request.app.state.pool.connection() as connection:
        return await accounts.verify(connection, body.token)


@router.post('/login')
async def login(body: Credentials, request: Request):
    async with request.app.state.pool.connection() as connection:
        return await accounts.login(connection, body.email, body.password)


@router.get('/me')
async def me(request: Request, authorization: str | None = Header(None)):
    async with request.app.state.pool.connection() as connection:
        return await accounts.me(connection, bearer(authorization))


@router.post('/logout')
async def logout(request: Request, authorization: str | None = Header(None)):
    async with request.app.state.pool.connection() as connection:
        return await accounts.logout(connection, bearer(authorization))


@router.get('')
async def account_list(request: Request, authorization: str | None = Header(None)):
    async with request.app.state.pool.connection() as connection:
        return await accounts.account_list(connection, bearer(authorization))


@router.patch('/{target_id}')
async def mutate(target_id: UUID, body: AccountChanges, request: Request, authorization: str | None = Header(None)):
    async with request.app.state.pool.connection() as connection:
        return await accounts.mutate(connection, bearer(authorization), target_id, body.model_dump(exclude_none=True))
