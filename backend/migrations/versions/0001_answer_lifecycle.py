"""Create the original answer lifecycle schema."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = '0001_answer_lifecycle'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'accounts',
        sa.Column('id', pg.UUID(), nullable=False),
        sa.Column('role', sa.Text(), nullable=False),
        sa.Column('verified', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('disabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('paid', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('context_epoch', sa.BigInteger(), nullable=False, server_default=sa.text('0')),
        sa.PrimaryKeyConstraint('id', name='accounts_pkey'),
        sa.CheckConstraint("role IN ('user','admin','super_admin')", name='accounts_role_check'),
    )
    op.create_table(
        'sessions',
        sa.Column('token_hash', sa.Text(), nullable=False),
        sa.Column('owner_id', pg.UUID(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint('token_hash', name='sessions_pkey'),
        sa.ForeignKeyConstraint(['owner_id'], ['accounts.id'], name='sessions_owner_id_fkey'),
    )
    op.create_table(
        'conversations',
        sa.Column('id', pg.UUID(), nullable=False),
        sa.Column('owner_id', pg.UUID(), nullable=False),
        sa.Column('context_epoch', sa.BigInteger(), nullable=False, server_default=sa.text('0')),
        sa.PrimaryKeyConstraint('id', name='conversations_pkey'),
        sa.ForeignKeyConstraint(['owner_id'], ['accounts.id'], name='conversations_owner_id_fkey'),
        sa.UniqueConstraint('id', 'owner_id', name='conversations_id_owner_id_key'),
    )
    op.create_table(
        'documents',
        sa.Column('id', pg.UUID(), nullable=False),
        sa.Column('owner_id', pg.UUID(), nullable=False),
        sa.Column('ready', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint('id', name='documents_pkey'),
        sa.ForeignKeyConstraint(['owner_id'], ['accounts.id'], name='documents_owner_id_fkey'),
    )
    op.create_table(
        'tabs',
        sa.Column('id', pg.UUID(), nullable=False),
        sa.Column('owner_id', pg.UUID(), nullable=False),
        sa.Column('proof_hash', sa.Text(), nullable=False),
        sa.Column('connection_epoch', sa.BigInteger(), nullable=False, server_default=sa.text('0')),
        sa.Column('deadline', sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint('id', name='tabs_pkey'),
        sa.ForeignKeyConstraint(['owner_id'], ['accounts.id'], name='tabs_owner_id_fkey'),
        sa.UniqueConstraint('id', 'owner_id', name='tabs_id_owner_id_key'),
    )
    service_state = op.create_table(
        'service_state',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=False),
        sa.Column('epoch', sa.BigInteger(), nullable=False, server_default=sa.text('0')),
        sa.Column('healthy_until', sa.DateTime(timezone=True), nullable=False, server_default='-infinity'),
        sa.PrimaryKeyConstraint('id', name='service_state_pkey'),
        sa.CheckConstraint('id=1', name='service_state_id_check'),
    )
    op.execute(service_state.insert().values(id=1))
    settings = op.create_table(
        'settings',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=False),
        sa.Column('overrides', pg.JSONB(), nullable=False, server_default='{}'),
        sa.Column('revision', sa.BigInteger(), nullable=False, server_default=sa.text('0')),
        sa.Column('applied_revision', sa.BigInteger(), nullable=False, server_default=sa.text('0')),
        sa.PrimaryKeyConstraint('id', name='settings_pkey'),
        sa.CheckConstraint('id=1', name='settings_id_check'),
    )
    op.execute(settings.insert().values(id=1))
    op.create_table(
        'settings_audit',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('actor_id', pg.UUID(), nullable=False),
        sa.Column('previous', pg.JSONB(), nullable=False),
        sa.Column('updated', pg.JSONB(), nullable=False),
        sa.Column('revision', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id', name='settings_audit_pkey'),
        sa.ForeignKeyConstraint(['actor_id'], ['accounts.id'], name='settings_audit_actor_id_fkey'),
    )
    op.create_table(
        'requests',
        sa.Column('id', pg.UUID(), nullable=False),
        sa.Column('conversation_id', pg.UUID(), nullable=False),
        sa.Column('owner_id', pg.UUID(), nullable=False),
        sa.Column('operation_key', pg.UUID(), nullable=False),
        sa.Column('fingerprint', sa.Text(), nullable=False),
        sa.Column('scope', pg.ARRAY(pg.UUID()), nullable=False),
        sa.Column('origin_tab', pg.UUID(), nullable=False),
        sa.Column('state', sa.Text(), nullable=False),
        sa.Column('reason', sa.Text()),
        sa.Column('execution_epoch', sa.BigInteger(), nullable=False),
        sa.Column('context_epoch', sa.BigInteger(), nullable=False),
        sa.Column('version', sa.BigInteger(), nullable=False, server_default=sa.text('1')),
        sa.Column('answer_text', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id', name='requests_pkey'),
        sa.CheckConstraint("state IN ('accepted','searching','queued','generating','completed','interrupted','failed')", name='requests_state_check'),
        sa.ForeignKeyConstraint(['conversation_id', 'owner_id'], ['conversations.id', 'conversations.owner_id'], name='requests_conversation_id_owner_id_fkey'),
        sa.ForeignKeyConstraint(['origin_tab', 'owner_id'], ['tabs.id', 'tabs.owner_id'], name='requests_origin_tab_owner_id_fkey'),
        sa.UniqueConstraint('owner_id', 'operation_key', name='requests_owner_id_operation_key_key'),
        sa.UniqueConstraint('id', 'conversation_id', name='requests_id_conversation_id_key'),
    )
    op.create_index('one_unfinished_request', 'requests', ['conversation_id'], unique=True,
                    postgresql_where=sa.text("state IN ('accepted','searching','queued','generating')"))
    op.create_table(
        'messages',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('request_id', pg.UUID(), nullable=False),
        sa.Column('conversation_id', pg.UUID(), nullable=False),
        sa.Column('role', sa.Text(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('excluded', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('source_flags', pg.JSONB(), nullable=False, server_default='{}'),
        sa.PrimaryKeyConstraint('id', name='messages_pkey'),
        sa.CheckConstraint("role IN ('user','assistant')", name='messages_role_check'),
        sa.ForeignKeyConstraint(['request_id', 'conversation_id'], ['requests.id', 'requests.conversation_id'], name='messages_request_id_conversation_id_fkey'),
        sa.UniqueConstraint('request_id', 'role', name='messages_request_id_role_key'),
    )
    op.create_table(
        'events',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('request_id', pg.UUID(), nullable=False),
        sa.Column('conversation_id', pg.UUID(), nullable=False),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('payload', pg.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='events_pkey'),
        sa.ForeignKeyConstraint(['request_id', 'conversation_id'], ['requests.id', 'requests.conversation_id'], name='events_request_id_conversation_id_fkey'),
    )
    op.create_index('events_conversation_cursor', 'events', ['conversation_id', 'id'])
    op.create_index('messages_conversation_order', 'messages', ['conversation_id', 'id'])
    op.create_index('requests_conversation_order', 'requests', ['conversation_id', 'created_at', 'id'])


def downgrade():
    raise RuntimeError('Destructive answer lifecycle baseline downgrade is unsupported')
