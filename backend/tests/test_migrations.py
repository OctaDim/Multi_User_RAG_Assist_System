import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest

from app.db import migrate
from app.resources import resource_path


@pytest.fixture
async def migration_database(postgres):
    name = 'migration_' + uuid4().hex
    with psycopg.connect(postgres, autocommit=True) as connection:
        connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    dsn = make_conninfo(postgres, dbname=name)
    try:
        yield dsn
    finally:
        with psycopg.connect(postgres, autocommit=True) as connection:
            connection.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


def legacy_prefix(dsn, count):
    with psycopg.connect(dsn) as connection:
        connection.execute('CREATE TABLE lifecycle_migrations(name text PRIMARY KEY, sha256 text NOT NULL)')
        for path in sorted((Path(__file__).parent / 'fixtures' / 'legacy_migrations').glob('*.sql'))[:count]:
            body = path.read_bytes()
            connection.execute(body.decode())
            connection.execute('INSERT INTO lifecycle_migrations VALUES (%s,%s)',
                               (path.name, hashlib.sha256(body).hexdigest()))


@pytest.mark.parametrize('prefix', range(7))
async def test_empty_and_every_legacy_prefix_reach_repeatable_alembic_head(migration_database, prefix):
    if prefix:
        legacy_prefix(migration_database, prefix)
        with psycopg.connect(migration_database) as connection:
            original_history = connection.execute('SELECT name,sha256 FROM lifecycle_migrations ORDER BY name').fetchall()
    await migrate(migration_database)
    await migrate(migration_database)
    with psycopg.connect(migration_database) as connection:
        assert connection.execute('SELECT version_num FROM alembic_version').fetchall() == [('0007_checkpoints',)]
        if prefix:
            assert connection.execute('SELECT name,sha256 FROM lifecycle_migrations ORDER BY name').fetchall() == original_history
        else:
            assert connection.execute("SELECT to_regclass('lifecycle_migrations')").fetchone() == (None,)
        assert connection.execute('SELECT v FROM checkpoint_migrations ORDER BY v').fetchall() == [(i,) for i in range(10)]


async def test_head_missing_table_is_rejected_without_repair(migration_database):
    await migrate(migration_database)
    with psycopg.connect(migration_database) as connection:
        connection.execute('DROP TABLE accounts_audit')
    with pytest.raises(RuntimeError, match='schema.*accounts_audit'):
        await migrate(migration_database)
    with psycopg.connect(migration_database) as connection:
        assert connection.execute("SELECT to_regclass('accounts_audit')").fetchone() == (None,)


async def test_api_lifespan_initializes_empty_database_before_ready(migration_database, monkeypatch):
    from app.main import create_app, lifespan

    monkeypatch.setenv('RAG_DATABASE_URL', migration_database)
    application = create_app()
    async with lifespan(application):
        with psycopg.connect(migration_database) as observer:
            assert observer.execute('SELECT version_num FROM alembic_version').fetchone() == ('0007_checkpoints',)
            assert observer.execute('SELECT count(*) FROM settings').fetchone() == (1,)
        database = application.state.database
    assert database.engine.pool.checkedout() == 0


@pytest.mark.parametrize('entrypoint', ['api', 'documents', 'generation', 'accounts'])
async def test_entrypoints_refuse_damaged_schema_before_serving_or_work(
        migration_database, monkeypatch, entrypoint):
    await migrate(migration_database)
    with psycopg.connect(migration_database) as observer:
        observer.execute('DROP TABLE accounts_audit')
    monkeypatch.setenv('RAG_DATABASE_URL', migration_database)
    if entrypoint == 'api':
        from app.main import create_app, lifespan
        application = create_app()
        with pytest.raises(RuntimeError, match='schema.*accounts_audit'):
            async with lifespan(application):
                pytest.fail('Damaged schema reached API readiness')
        assert not hasattr(application.state, 'database')
    elif entrypoint == 'documents':
        from app.document_worker import run
        with pytest.raises(RuntimeError, match='schema.*accounts_audit'):
            await run()
    elif entrypoint == 'generation':
        from app.generation import Supervisor
        supervisor = Supervisor(migration_database)
        with pytest.raises(RuntimeError, match='schema.*accounts_audit'):
            await supervisor.run()
        assert supervisor.child is None
    else:
        process = await asyncio.create_subprocess_exec(
            sys.executable, '-m', 'app.accounts', '--email', 'operator@example.test',
            cwd=Path(__file__).parents[1], stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), 15)
        assert process.returncode != 0 and not stdout
        assert b'accounts_audit' in stderr
    with psycopg.connect(migration_database) as observer:
        assert observer.execute("SELECT to_regclass('accounts_audit')").fetchone() == (None,)


async def test_concurrent_async_calls_do_not_corrupt_alembic_context(migration_database):
    await asyncio.wait_for(asyncio.gather(migrate(migration_database), migrate(migration_database)), 15)
    with psycopg.connect(migration_database) as connection:
        assert connection.execute('SELECT version_num FROM alembic_version').fetchall() == [('0007_checkpoints',)]
        assert connection.execute("SELECT to_regclass('lifecycle_migrations')").fetchone() == (None,)


@pytest.mark.parametrize('damage, diagnostic', [
    ('ALTER TABLE requests DROP CONSTRAINT request_session_owner', 'constraints'),
    ('ALTER TABLE source_chunks DISABLE TRIGGER immutable_chunks', 'triggers'),
    ('DELETE FROM settings', 'singleton.*settings'),
    ("UPDATE lifecycle_migrations SET sha256='wrong'", 'checksum'),
    ("INSERT INTO lifecycle_migrations VALUES ('007_unknown.sql','unknown')", 'history'),
    ("DELETE FROM lifecycle_migrations WHERE name LIKE '003%'", 'history'),
    ("UPDATE alembic_version SET version_num='unknown'", 'Unknown Alembic'),
    ('INSERT INTO checkpoint_migrations VALUES (10)', 'checkpoint_migrations'),
    ('DELETE FROM checkpoint_migrations WHERE v=4', 'checkpoint_migrations'),
])
async def test_current_head_rejects_schema_and_history_damage(migration_database, damage, diagnostic):
    legacy_prefix(migration_database, 6)
    await migrate(migration_database)
    with psycopg.connect(migration_database) as connection:
        connection.execute(damage)
    with pytest.raises(RuntimeError, match=diagnostic):
        await migrate(migration_database)


@pytest.mark.parametrize('prefix', [2, 4, 6])
async def test_adoption_preserves_lease_history_and_once_only_terminal_effects(migration_database, prefix):
    legacy_prefix(migration_database, prefix)
    account, conversation, tab, request = [uuid4() for _ in range(4)]
    with psycopg.connect(migration_database) as connection:
        lease_table = 'service_state' if prefix < 3 else 'coordinator_lease'
        connection.execute(f"UPDATE {lease_table} SET epoch=17,healthy_until='2040-01-01 UTC'")
        connection.execute('INSERT INTO accounts(id,role) VALUES (%s,\'user\')', (account,))
        connection.execute('INSERT INTO conversations(id,owner_id) VALUES (%s,%s)', (conversation, account))
        connection.execute('INSERT INTO tabs(id,owner_id,proof_hash) VALUES (%s,%s,\'proof\')', (tab, account))
        state = 'accepted' if prefix < 5 else 'completed'
        connection.execute('''INSERT INTO requests(id,conversation_id,owner_id,operation_key,fingerprint,scope,
            origin_tab,state,execution_epoch,context_epoch) VALUES (%s,%s,%s,%s,'fingerprint','{}',%s,%s,0,0)''',
            (request,conversation,account,uuid4(),tab,state))
        connection.execute("INSERT INTO messages(request_id,conversation_id,role,text) VALUES (%s,%s,'assistant','retained answer')",
                           (request,conversation))
    await migrate(migration_database)
    await migrate(migration_database)
    with psycopg.connect(migration_database) as connection:
        assert connection.execute("SELECT epoch,healthy_until='2040-01-01 UTC'::timestamptz FROM coordinator_lease").fetchone() == (17,True)
        assert connection.execute('SELECT state,reason FROM requests WHERE id=%s',(request,)).fetchone() == (
            ('interrupted','session_binding_missing') if prefix < 5 else ('completed',None))
        assert connection.execute('SELECT count(*) FROM events WHERE request_id=%s AND kind=\'terminal\'',(request,)).fetchone() == ((1,) if prefix < 5 else (0,))
        assert connection.execute('SELECT text,excluded FROM messages WHERE request_id=%s',(request,)).fetchone() == ('retained answer',prefix < 5)


@pytest.mark.parametrize('prefix', range(11))
@pytest.mark.parametrize('crash_after_ddl', [False, True])
async def test_checkpoint_prefix_and_ddl_before_marker_preserve_payload(migration_database, prefix, crash_after_ddl):
    from langgraph.checkpoint.postgres.base import MIGRATIONS

    with psycopg.connect(migration_database, autocommit=True) as connection:
        for version, statement in enumerate(MIGRATIONS[:prefix]):
            connection.execute(statement)
            connection.execute('INSERT INTO checkpoint_migrations VALUES (%s)',(version,))
        if crash_after_ddl and prefix < len(MIGRATIONS):
            connection.execute(MIGRATIONS[prefix])
        if prefix >= 2 or (crash_after_ddl and prefix == 1):
            connection.execute("INSERT INTO checkpoints(thread_id,checkpoint_id,checkpoint) VALUES ('retained','id','{\"payload\":42}')")
    await migrate(migration_database)
    await migrate(migration_database)
    with psycopg.connect(migration_database) as connection:
        assert connection.execute('SELECT v FROM checkpoint_migrations ORDER BY v').fetchall() == [(i,) for i in range(10)]
        if prefix >= 2 or (crash_after_ddl and prefix == 1):
            assert connection.execute("SELECT checkpoint FROM checkpoints WHERE thread_id='retained'").fetchone() == ({'payload':42},)


async def test_checkpoint_unknown_unjournaled_shape_stops_before_application_ddl(migration_database):
    with psycopg.connect(migration_database) as connection:
        connection.execute('CREATE TABLE checkpoints(bogus text)')
    with pytest.raises(RuntimeError, match='checkpoint prefix.*schema mismatch'):
        await migrate(migration_database)
    with psycopg.connect(migration_database) as connection:
        assert connection.execute("SELECT to_regclass('accounts')").fetchone() == (None,)


@pytest.fixture
def prepared_next_revision(tmp_path):
    root = tmp_path / 'migrations'
    shutil.copytree(resource_path('migrations'), root, ignore=shutil.ignore_patterns('__pycache__'))
    profile = json.loads((root / 'contracts' / '0007_checkpoints.json').read_text())
    columns = profile['application']['columns']
    position = max(i for i, row in enumerate(columns) if row[0] == 'accounts') + 1
    columns.insert(position, ['accounts','prepared_note','text',False,'','',None])
    (root / 'contracts' / '0008_prepared.json').write_text(json.dumps(profile))
    revision = root / 'versions' / '0008_prepared.py'
    revision.write_text('''from alembic import op
import sqlalchemy as sa
revision = '0008_prepared'
down_revision = '0007_checkpoints'

def upgrade():
    op.add_column('accounts', sa.Column('prepared_note', sa.Text()))

def downgrade():
    raise RuntimeError('unsupported')
''')
    return root, revision


async def test_prepared_future_revision_uses_its_own_contract_without_changing_legacy_profiles(
        migration_database, prepared_next_revision, monkeypatch):
    await migrate(migration_database)
    root, _ = prepared_next_revision
    monkeypatch.setattr('app.db.resource_path', lambda name: root)
    legacy = (root / 'contracts' / 'application.json').read_bytes()
    await migrate(migration_database)
    await migrate(migration_database)
    assert (root / 'contracts' / 'application.json').read_bytes() == legacy
    with psycopg.connect(migration_database) as connection:
        assert connection.execute('SELECT version_num FROM alembic_version').fetchone() == ('0008_prepared',)
        connection.execute('ALTER TABLE accounts DROP COLUMN prepared_note')
    with pytest.raises(RuntimeError, match='schema mismatch.*prepared_note'):
        await migrate(migration_database)


async def test_revision_failure_rolls_back_ddl_data_and_releases_lock(migration_database, monkeypatch, tmp_path):
    await migrate(migration_database)
    root = tmp_path / 'migrations'
    shutil.copytree(resource_path('migrations'), root, ignore=shutil.ignore_patterns('__pycache__'))
    monkeypatch.setattr('app.db.resource_path', lambda name: root)
    (root / 'versions' / '0008_failure.py').write_text('''from alembic import op
import sqlalchemy as sa
revision = '0008_failure'
down_revision = '0007_checkpoints'

def upgrade():
    op.add_column('accounts', sa.Column('rolled_back', sa.Text()))
    settings = sa.table('settings', sa.column('revision'))
    op.get_bind().execute(settings.update().values(revision=999))
    raise RuntimeError('injected revision failure')
''')
    for _ in range(2):
        with pytest.raises(RuntimeError, match='injected revision failure'):
            await migrate(migration_database)
        with psycopg.connect(migration_database) as connection:
            assert connection.execute('SELECT version_num FROM alembic_version').fetchone() == ('0007_checkpoints',)
            assert connection.execute('SELECT revision FROM settings').fetchone() == (0,)
            assert connection.execute("SELECT count(*) FROM information_schema.columns WHERE table_name='accounts' AND column_name='rolled_back'").fetchone() == (0,)
            assert connection.execute("SELECT pg_try_advisory_lock(hashtextextended('rag:migrations',0))").fetchone() == (True,)


async def alembic_cli(dsn, *arguments):
    return await asyncio.create_subprocess_exec(
        sys.executable, '-m', 'alembic', '-c', str(Path(__file__).parents[1] / 'alembic.ini'), *arguments,
        env={**os.environ, 'RAG_DATABASE_URL': dsn},
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )


async def test_independent_cli_processes_wait_for_migration_lock_and_recheck(migration_database):
    application_name = 'migration_' + uuid4().hex
    dsn = make_conninfo(migration_database, application_name=application_name)
    with psycopg.connect(migration_database, autocommit=True) as lock:
        lock.execute("SELECT pg_advisory_lock(hashtextextended('rag:migrations',0))")
        first, second = await asyncio.gather(alembic_cli(dsn,'upgrade','head'), alembic_cli(dsn,'upgrade','head'))
        try:
            async with asyncio.timeout(15):
                while lock.execute("SELECT count(*) FROM pg_stat_activity WHERE application_name=%s AND wait_event='advisory'",(application_name,)).fetchone()[0] != 2:
                    await asyncio.sleep(0.02)
            assert lock.execute("SELECT to_regclass('accounts')").fetchone() == (None,)
        finally:
            lock.execute("SELECT pg_advisory_unlock(hashtextextended('rag:migrations',0))")
        for process in (first,second):
            stdout, stderr = await asyncio.wait_for(process.communicate(),15)
            assert process.returncode == 0, (stdout.decode(),stderr.decode())
    await migrate(migration_database)


async def test_cli_autogenerate_excludes_infrastructure_and_refuses_offline_and_downgrade(migration_database):
    await migrate(migration_database)
    for arguments, expected in [
        (('check',), 'No new upgrade operations detected'),
        (('upgrade','head','--sql'), 'Offline migration is unsupported'),
        (('downgrade','base'), 'downgrade is unsupported'),
    ]:
        process = await alembic_cli(migration_database, *arguments)
        stdout, stderr = await asyncio.wait_for(process.communicate(),15)
        assert expected in (stdout+stderr).decode()
        assert (process.returncode == 0) == (arguments == ('check',))
    await migrate(migration_database)


async def test_cli_current_on_legacy_database_does_not_adopt_or_create_history(migration_database):
    legacy_prefix(migration_database, 2)
    process = await alembic_cli(migration_database, 'current')
    stdout, stderr = await asyncio.wait_for(process.communicate(),15)
    assert process.returncode == 0, (stdout.decode(),stderr.decode())
    with psycopg.connect(migration_database) as connection:
        assert connection.execute("SELECT to_regclass('alembic_version')").fetchone() == (None,)
        assert connection.execute('SELECT count(*) FROM lifecycle_migrations').fetchone() == (2,)


async def test_cli_upgrade_can_stop_at_historical_revision_then_reach_head(migration_database):
    process = await alembic_cli(migration_database, 'upgrade','0003_generation_ownership')
    stdout, stderr = await asyncio.wait_for(process.communicate(),15)
    assert process.returncode == 0, (stdout.decode(),stderr.decode())
    with psycopg.connect(migration_database) as connection:
        assert connection.execute('SELECT version_num FROM alembic_version').fetchone() == ('0003_generation_ownership',)
        assert connection.execute("SELECT to_regclass('email_verifications'),to_regclass('checkpoint_migrations')").fetchone() == (None,None)
    await migrate(migration_database)
