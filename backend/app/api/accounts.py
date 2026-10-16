from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, ConfigDict, Field

from app import accounts
from app.auth import bearer
from app.configuration import load_settings


INPUTS = load_settings('policy')['inputs']


router = APIRouter(prefix='/api/accounts')


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=INPUTS['email_min'], max_length=INPUTS['email_max'])
    password: str = Field(min_length=INPUTS['password_min'], max_length=INPUTS['password_max'])


class Registration(Credentials):
    invitation: str | None = Field(default=None, min_length=1, max_length=INPUTS['token_max'])


class Verification(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: str = Field(min_length=1, max_length=INPUTS['token_max'])


class AccountChanges(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    role: Literal['user', 'admin', 'super_admin'] | None = None
    active: bool | None = None
    disabled: bool | None = None


@router.post('/register', status_code=201)
async def register(body: Registration, request: Request):
    async with request.app.state.database.session() as session:
        return await accounts.register(session, body.email, body.password, body.invitation)


@router.post('/verify')
async def verify(body: Verification, request: Request):
    async with request.app.state.database.session() as session:
        return await accounts.verify(session, body.token)


@router.post('/login')
async def login(body: Credentials, request: Request):
    async with request.app.state.database.session() as session:
        return await accounts.login(session, body.email, body.password)


@router.get('/me')
async def me(request: Request, authorization: str | None = Header(None)):
    async with request.app.state.database.session() as session:
        return await accounts.me(session, bearer(authorization))


@router.post('/logout')
async def logout(request: Request, authorization: str | None = Header(None)):
    async with request.app.state.database.session() as session:
        return await accounts.logout(session, bearer(authorization))


@router.get('')
async def account_list(request: Request, authorization: str | None = Header(None)):
    async with request.app.state.database.session() as session:
        return await accounts.account_list(session, bearer(authorization))


@router.patch('/{target_id}')
async def mutate(target_id: UUID, body: AccountChanges, request: Request, authorization: str | None = Header(None)):
    async with request.app.state.database.session() as session:
        return await accounts.mutate(session, bearer(authorization), target_id, body.model_dump(exclude_none=True))
