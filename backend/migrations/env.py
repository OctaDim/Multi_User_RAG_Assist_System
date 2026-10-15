import asyncio
import importlib.util
from pathlib import Path

from alembic import context
from alembic.script import ScriptDirectory
from sqlalchemy import func, select

from app.db import Database, database_url
from app.models import Base

config = context.config
spec = importlib.util.spec_from_file_location('rag_schema_contract', Path(__file__).with_name('schema_contract.py'))
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)
config.attributes['schema_contract'] = contract
script = ScriptDirectory.from_config(config)
revisions = {revision.revision for revision in script.walk_revisions()}
command_name = config.attributes.get('command')
if command_name is None and config.cmd_opts is not None:
    command_name = config.cmd_opts.cmd[0].__name__


def include_object(obj, name, kind, reflected, compare_to):
    return kind != 'table' or name in Base.metadata.tables or name in contract.APPLICATION_TABLES


def run_migrations(connection):
    connection.execute(select(func.pg_advisory_lock(func.hashtextextended('rag:migrations', 0))))
    try:
        adopted_revision = contract.validate(connection, revisions)
        connection.commit()  # Finish preflight autobegin before Alembic owns the DDL transaction.
        context.configure(connection=connection, target_metadata=Base.metadata,
                          include_object=include_object, compare_type=True,
                          dont_mutate=command_name not in ('upgrade', 'downgrade', 'stamp', 'ensure_version'))
        with context.begin_transaction():
            if command_name == 'upgrade' and adopted_revision:
                context.get_context().stamp(script, adopted_revision)
            context.run_migrations()
            target = context.get_revision_argument() if command_name == 'upgrade' else None
            contract.validate(connection, revisions, expected=target)
    finally:
        connection.rollback()
        connection.execute(select(func.pg_advisory_unlock(func.hashtextextended('rag:migrations', 0))))
        connection.commit()


async def online():
    database = Database(config.attributes.get('dsn') or database_url())
    try:
        async with database.connection() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await database.dispose()


if context.is_offline_mode():
    raise RuntimeError('Offline migration is unsupported: adoption requires live schema and history validation')
elif config.attributes.get('connection') is not None:
    run_migrations(config.attributes['connection'])
else:
    asyncio.run(online())
