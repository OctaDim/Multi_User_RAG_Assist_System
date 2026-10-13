import argparse
import asyncio
import os
from contextlib import suppress
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
import uvicorn

from app.api import accounts, answers, documents, settings, tabs
from app.events import deadlines
from app.auth import AccessError
from app.db import database_url


@asynccontextmanager
async def lifespan(app):
    async with AsyncConnectionPool(database_url(), open=False, kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0}) as pool:
        await pool.wait()
        async with pool.connection() as connection:
            await connection.execute("SELECT id FROM service_state WHERE id=1")
        app.state.pool = pool
        deadline_task = asyncio.create_task(deadlines(pool))
        try:
            yield
        finally:
            deadline_task.cancel()
            with suppress(asyncio.CancelledError):
                await deadline_task


async def access_error(request: Request, error: AccessError):
    return JSONResponse(status_code=error.status, content={"error": error.code})


async def invalid_input(request: Request, error: RequestValidationError):
    # Pydantic's default response echoes rejected input, including passwords/tokens.
    return JSONResponse(status_code=422, content={'error': 'invalid_input'})


def create_app():
    application = FastAPI(lifespan=lifespan)
    origin = os.environ.get('RAG_FRONTEND_ORIGIN', '').rstrip('/')
    application.add_middleware(CORSMiddleware, allow_origins=[origin] if origin else [],
                               allow_methods=['GET', 'POST', 'PATCH', 'PUT', 'DELETE'],
                               allow_headers=['Authorization', 'Content-Type', 'X-Tab-Proof'])
    for router in (accounts.router, answers.router, documents.router, settings.router, tabs.router):
        application.include_router(router)
    application.add_exception_handler(AccessError, access_error)
    application.add_exception_handler(RequestValidationError, invalid_input)
    return application


app = create_app()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("app.main:app", host=args.host, port=args.port)
