import argparse
import asyncio
import os
from contextlib import suppress
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.api import accounts, answers, documents, settings, tabs
from app.events import deadlines
from app.auth import AccessError
from app.db import Database, database_url, migrate
from app.handoff import GuardedH11Protocol, HandoffMiddleware
from app.configuration import load_service_config


@asynccontextmanager
async def lifespan(app):
    dsn = database_url()
    database = Database(dsn)
    deadline_task = None
    try:
        await migrate(dsn)
        app.state.database = database
        deadline_task = asyncio.create_task(deadlines(database))
        yield
    finally:
        try:
            if deadline_task is not None:
                deadline_task.cancel()
                with suppress(asyncio.CancelledError):
                    await deadline_task
        finally:
            await database.dispose()


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
                               allow_headers=['Authorization', 'Content-Type', 'X-Tab-Proof',
                                              'X-Connection-Epoch', 'X-Heartbeat-Challenge', 'Last-Event-ID'])
    application.add_middleware(HandoffMiddleware)
    for router in (accounts.router, answers.router, documents.router, settings.router, tabs.router):
        application.include_router(router)
    application.add_exception_handler(AccessError, access_error)
    application.add_exception_handler(RequestValidationError, invalid_input)
    return application


app = create_app()


def main():
    config = load_service_config()['api']
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=config['host'])
    parser.add_argument("--port", type=int, default=config['port'])
    args = parser.parse_args()
    uvicorn.run("app.main:app", host=args.host, port=args.port, http=GuardedH11Protocol, loop='asyncio')


if __name__ == '__main__':
    main()
