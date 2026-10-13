import argparse
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
import uvicorn

from app.api import answers, settings
from app.auth import AccessError
from app.db import database_url


@asynccontextmanager
async def lifespan(app):
    async with AsyncConnectionPool(database_url(), open=False, kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0}) as pool:
        await pool.wait()
        async with pool.connection() as connection:
            await connection.execute("SELECT id FROM service_state WHERE id=1")
        app.state.pool = pool
        app.state.checkpointer = AsyncPostgresSaver(pool)
        yield


app = FastAPI(lifespan=lifespan)
app.include_router(answers.router)
app.include_router(settings.router)


@app.exception_handler(AccessError)
async def access_error(request: Request, error: AccessError):
    return JSONResponse(status_code=error.status, content={"error": error.code})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("app.main:app", host=args.host, port=args.port)
