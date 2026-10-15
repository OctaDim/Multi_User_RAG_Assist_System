import asyncio
import hashlib
import os
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.resources import resource_path


class Database:
    def __init__(self, dsn):
        parameters = conninfo_to_dict(dsn)
        url = URL.create(
            "postgresql+psycopg",
            username=parameters.pop("user", None),
            password=parameters.pop("password", None),
            database=parameters.pop("dbname", None),
        )
        self.engine = create_async_engine(url, connect_args=parameters, pool_pre_ping=True, hide_parameters=True)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def connection(self):
        async with self.engine.connect() as connection:
            yield connection

    @asynccontextmanager
    async def session(self):
        async with self.session_factory() as session:
            yield session

    async def dispose(self):
        await self.engine.dispose()


def database_url():
    return os.environ["RAG_DATABASE_URL"]


async def migrate(dsn):
    async with await AsyncConnection.connect(dsn, autocommit=True, row_factory=dict_row) as connection:
        await connection.execute("SELECT pg_advisory_lock(hashtextextended('rag:migrations',0))")
        try:
            await connection.execute("CREATE TABLE IF NOT EXISTS lifecycle_migrations(name text PRIMARY KEY, sha256 text NOT NULL)")
            for path in sorted(resource_path("migrations").glob("*.sql")):
                body = path.read_bytes()
                digest = hashlib.sha256(body).hexdigest()
                row = await (await connection.execute("SELECT sha256 FROM lifecycle_migrations WHERE name=%s", (path.name,))).fetchone()
                if row:
                    if row["sha256"] != digest:
                        raise RuntimeError(f"Applied migration changed: {path.name}")
                    continue
                async with connection.transaction():
                    await connection.execute(body.decode("utf-8"))
                    await connection.execute("INSERT INTO lifecycle_migrations VALUES (%s,%s)", (path.name, digest))
            await AsyncPostgresSaver(connection).setup()
        finally:
            await connection.execute("SELECT pg_advisory_unlock(hashtextextended('rag:migrations',0))")


def main():
    asyncio.run(migrate(database_url()))
