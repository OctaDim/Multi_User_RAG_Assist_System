"""Frozen PostgreSQL contracts for legacy adoption and prepared Alembic revisions."""
import json
from pathlib import Path

ROOT = Path(__file__).parent
APPLICATION_TABLES = (
    'accounts', 'sessions', 'conversations', 'documents', 'tabs', 'service_state',
    'settings', 'settings_audit', 'requests', 'messages', 'events',
    'source_revisions', 'source_pages', 'source_chunks', 'request_sources',
    'graph_bindings', 'coordinator_lease', 'email_verifications',
    'account_invitations', 'accounts_audit', 'document_policies', 'document_files',
    'document_page_texts', 'document_policy_audit', 'available_source_revisions',
)
CHECKPOINT_TABLES = ('checkpoint_migrations', 'checkpoints', 'checkpoint_blobs', 'checkpoint_writes')


def load(name):
    return json.loads((ROOT / 'contracts' / name).read_text())


def snapshot(connection, names, *, functions=False):
    """Read only project-owned objects, with definitions independent of object OIDs."""
    names = list(names)
    queries = {
        'relations': '''SELECT c.relname, c.relkind FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relname=ANY(%s) ORDER BY 1''',
        'columns': '''SELECT c.relname, a.attname, format_type(a.atttypid,a.atttypmod),
            a.attnotnull, a.attidentity, a.attgenerated, pg_get_expr(d.adbin,d.adrelid)
            FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
            WHERE n.nspname='public' AND c.relname=ANY(%s) AND a.attnum>0 AND NOT a.attisdropped
            ORDER BY c.relname,a.attnum''',
        'constraints': '''SELECT c.relname, con.conname, pg_get_constraintdef(con.oid), con.convalidated
            FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relname=ANY(%s) ORDER BY 1,2''',
        'indexes': '''SELECT c.relname, i.relname, pg_get_indexdef(i.oid), x.indisvalid, x.indisready
            FROM pg_index x JOIN pg_class c ON c.oid=x.indrelid JOIN pg_class i ON i.oid=x.indexrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relname=ANY(%s) ORDER BY 1,2''',
        'triggers': '''SELECT c.relname, t.tgname, pg_get_triggerdef(t.oid), t.tgenabled
            FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relname=ANY(%s) AND NOT t.tgisinternal ORDER BY 1,2''',
        'views': '''SELECT c.relname, pg_get_viewdef(c.oid) FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relname=ANY(%s) AND c.relkind='v' ORDER BY 1''',
    }
    result = {key: [list(row) for row in connection.exec_driver_sql(query, (names,))]
              for key, query in queries.items()}
    if functions:
        result['functions'] = [list(row) for row in connection.exec_driver_sql('''
            SELECT p.proname, pg_get_functiondef(p.oid) FROM pg_proc p
            JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='public' AND p.proname='protect_published_revision'
            ORDER BY p.oid::regprocedure::text''')]
    return result


def require_shape(actual, expected, label):
    for kind, rows in expected.items():
        if actual[kind] != rows:
            missing = [row for row in rows if row not in actual[kind]]
            unexpected = [row for row in actual[kind] if row not in rows]
            raise RuntimeError(f'{label} schema mismatch ({kind}): missing={missing}; unexpected={unexpected}')


def exists(connection, name):
    return connection.exec_driver_sql('SELECT to_regclass(%s)', ('public.' + name,)).scalar() is not None


def application_prefix(connection, *, schema=True):
    manifest = load('application.json')
    rows = []
    if exists(connection, 'lifecycle_migrations'):
        require_shape(snapshot(connection, ['lifecycle_migrations']), manifest['ledger'], 'lifecycle_migrations')
        rows = list(connection.exec_driver_sql('SELECT name,sha256 FROM lifecycle_migrations ORDER BY name'))
    expected = list(manifest['checksums'].items())
    if [tuple(row) for row in rows] != expected[:len(rows)]:
        raise RuntimeError('Unknown, non-contiguous, or checksum-mismatched lifecycle_migrations history')
    prefix = len(rows)
    if schema:
        require_shape(snapshot(connection, APPLICATION_TABLES, functions=True), manifest['profiles'][prefix],
                      f'application prefix {prefix}')
    for name in ('service_state', 'settings', 'coordinator_lease'):
        if exists(connection, name) and connection.exec_driver_sql(f'SELECT id FROM {name}').all() != [(1,)]:
            raise RuntimeError(f'application schema missing required singleton: {name}')
    return prefix


def checkpoint_prefix(connection):
    profiles = load('checkpoints.json')['profiles']
    actual = snapshot(connection, CHECKPOINT_TABLES)
    rows = []
    if exists(connection, 'checkpoint_migrations'):
        # Validate the ledger's shape before reading its version column.
        ledger = snapshot(connection, ['checkpoint_migrations'])
        require_shape(ledger, load('checkpoints.json')['ledger'], 'checkpoint_migrations')
        rows = [row[0] for row in connection.exec_driver_sql('SELECT v FROM checkpoint_migrations ORDER BY v')]
    if rows != list(range(len(rows))) or len(rows) > 10:
        raise RuntimeError('Unknown or non-contiguous checkpoint_migrations history')
    prefix = len(rows)
    if actual != profiles[prefix] and (prefix == 10 or actual != profiles[prefix + 1]):
        # Old saver autocommitted DDL before its marker; only the exact next shape is safe.
        require_shape(actual, profiles[prefix], f'checkpoint prefix {prefix}')
    return prefix


def validate(connection, revisions, *, expected=None):
    version = None
    if exists(connection, 'alembic_version'):
        rows = connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalars().all()
        if rows and (len(rows) != 1 or rows[0] not in revisions):
            raise RuntimeError(f'Unknown Alembic revision: {rows}')
        version = rows[0] if rows else None
    prefix = application_prefix(connection, schema=version is None)
    if version is None:
        checkpoint_prefix(connection)
    else:
        path = ROOT / 'contracts' / f'{version}.json'
        if not path.is_file():
            raise RuntimeError(f'Missing frozen schema contract for Alembic revision {version}')
        profile = load(path.name)
        for group, names in [('application', APPLICATION_TABLES), ('checkpoints', CHECKPOINT_TABLES)]:
            if profile[group] is None:
                checkpoint_prefix(connection)
                continue
            names = sorted(set(names) | {row[0] for row in profile[group]['relations']})
            require_shape(snapshot(connection, names, functions=group == 'application'),
                          profile[group], f'{version} {group}')
        if profile['checkpoint_history'] is not None:
            history = connection.exec_driver_sql('SELECT v FROM checkpoint_migrations ORDER BY v').scalars().all()
            if history != profile['checkpoint_history']:
                raise RuntimeError(f'{version} checkpoint_migrations history mismatch: {history}')
    if expected is not None and version != expected:
        raise RuntimeError(f'Expected Alembic head {expected}, got {version}')
    if version is None and prefix:
        return load('application.json')['revisions'][prefix - 1]
    return None


def upgrade_checkpoints(connection):
    prefix = checkpoint_prefix(connection)
    for version, statement in enumerate(load('checkpoints.json')['steps'][prefix:], prefix):
        connection.exec_driver_sql(statement)
        connection.exec_driver_sql('INSERT INTO checkpoint_migrations VALUES (%s)', (version,))
