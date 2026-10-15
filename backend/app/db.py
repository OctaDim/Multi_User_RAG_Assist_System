import asyncio
import os
import threading
from contextlib import asynccontextmanager

from psycopg.conninfo import conninfo_to_dict
from alembic import command
from alembic.config import Config
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


# Alembic's context/op proxies are process globals, including across async calls.
_migration_command_lock = threading.Lock()


async def migrate(dsn):
    def upgrade():
        with _migration_command_lock:
            config = Config()
            config.set_main_option('script_location', str(resource_path('migrations')))
            config.attributes['dsn'] = dsn
            config.attributes['command'] = 'upgrade'
            command.upgrade(config, 'head')
    await asyncio.to_thread(upgrade)


def main():
    asyncio.run(migrate(database_url()))
