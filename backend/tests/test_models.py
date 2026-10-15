import subprocess
import sys
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import CheckConstraint, UniqueConstraint, inspect, select

from app.db import Database


def test_model_registry_contains_all_application_tables():
    from app.models import Base

    assert set(Base.metadata.tables) == {
        'accounts', 'sessions', 'conversations', 'documents', 'tabs',
        'service_state', 'settings', 'settings_audit', 'requests', 'messages',
        'events', 'source_revisions', 'source_pages', 'source_chunks',
        'request_sources', 'graph_bindings', 'coordinator_lease',
        'email_verifications', 'account_invitations', 'accounts_audit',
        'document_policies', 'document_files', 'document_page_texts',
        'document_policy_audit',
    }


def test_importing_models_needs_no_engine_or_connection():
    result = subprocess.run(
        [sys.executable, '-c', '''
import socket
import sqlalchemy
import sqlalchemy.ext.asyncio

def forbidden(*args, **kwargs):
    raise AssertionError('Model import attempted database I/O or engine creation')

socket.socket.connect = forbidden
sqlalchemy.create_engine = forbidden
sqlalchemy.ext.asyncio.create_async_engine = forbidden
from app.models.source_chunk import SourceChunk
from app.models import Base
assert SourceChunk.metadata is Base.metadata
'''],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def _compare_catalog(connection):
    from app.models import Base

    metadata = Base.metadata
    inspector = inspect(connection)
    context = MigrationContext.configure(connection, opts={
        'include_object': lambda obj, name, kind, reflected, compared:
            kind != 'table' or name in metadata.tables,
        # Defaults are compared below without executing volatile expressions.
        'compare_server_default': False,
    })
    assert compare_metadata(context, metadata) == []

    # Alembic does not compare CHECK constraints or partial-index predicates.
    for name, table in metadata.tables.items():
        assert {c.name: str(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)} == {
            c['name']: c['sqltext'] for c in inspector.get_check_constraints(name)
        }, name
        primary = inspector.get_pk_constraint(name)
        assert (table.primary_key.name, list(table.primary_key.columns.keys())) == (
            primary['name'], primary['constrained_columns'],
        ), name
        assert {c.name: list(c.columns.keys()) for c in table.constraints if isinstance(c, UniqueConstraint)} == {
            c['name']: c['column_names'] for c in inspector.get_unique_constraints(name)
        }, name
        assert {c.name: (list(c.column_keys), [e.target_fullname for e in c.elements]) for c in table.foreign_key_constraints} == {
            c['name']: (c['constrained_columns'], [f"{c['referred_table']}.{column}" for column in c['referred_columns']])
            for c in inspector.get_foreign_keys(name)
        }, name
        for index in inspector.get_indexes(name):
            if index.get('duplicates_constraint'):
                continue
            mapped = next(i for i in table.indexes if i.name == index['name'])
            predicate = mapped.dialect_options['postgresql']['where']
            assert (str(predicate) if predicate is not None else None) == index.get('dialect_options', {}).get('postgresql_where')
        for column in inspector.get_columns(name):
            mapped = table.c[column['name']]
            assert mapped.default is None
            assert mapped.type.compile(dialect=connection.dialect) == column['type'].compile(dialect=connection.dialect)
            if column.get('identity'):
                assert mapped.identity is not None and mapped.identity.always == column['identity']['always']
            else:
                assert mapped.identity is None
                default = str(mapped.server_default.arg) if mapped.server_default is not None else None
                assert default == column['default'], (name, column['name'])


async def test_models_match_existing_migration_catalog(environment):
    database = Database(environment['dsn'])
    try:
        async with database.connection() as connection:
            await connection.run_sync(_compare_catalog)
    finally:
        await database.dispose()


async def test_vector_comparator_uses_existing_embedding(environment):
    from app.models import SourceChunk

    database = Database(environment['dsn'])
    try:
        async with database.session() as session:
            distance = await session.scalar(select(
                SourceChunk.embedding.cosine_distance([1.0] + [0.0] * 383),
            ).where(SourceChunk.id == environment['chunk']))
            assert distance == 0
    finally:
        await database.dispose()
