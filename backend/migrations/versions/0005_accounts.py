"""Add credentials, session ownership and account audit history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = '0005_accounts'
down_revision = '0004_tab_presence'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('accounts', sa.Column('email', sa.Text()))
    op.create_unique_constraint('accounts_email_key', 'accounts', ['email'])
    op.add_column('accounts', sa.Column('password_hash', sa.Text()))
    op.create_check_constraint('account_credentials_pair', 'accounts', '(email IS NULL) = (password_hash IS NULL)')
    op.add_column('sessions', sa.Column('id', pg.UUID(), nullable=False, server_default=sa.func.gen_random_uuid()))
    op.create_unique_constraint('session_identity', 'sessions', ['id', 'owner_id'])
    op.add_column('requests', sa.Column('origin_session', pg.UUID()))
    op.create_foreign_key('request_session_owner', 'requests', 'sessions', ['origin_session', 'owner_id'], ['id', 'owner_id'])

    # Existing admissions have no provable originating session; retain and fence them.
    requests = sa.table('requests',
        sa.column('id', pg.UUID()), sa.column('conversation_id', pg.UUID()),
        sa.column('state', sa.Text()), sa.column('reason', sa.Text()), sa.column('version', sa.BigInteger()))
    events = sa.table('events',
        sa.column('request_id', pg.UUID()), sa.column('conversation_id', pg.UUID()),
        sa.column('kind', sa.Text()), sa.column('payload', pg.JSONB()))
    stopped = requests.update().where(
        requests.c.state.in_(['accepted', 'searching', 'queued', 'generating']),
    ).values(state='interrupted', reason='session_binding_missing', version=requests.c.version + 1).returning(
        requests.c.id, requests.c.conversation_id, requests.c.state, requests.c.reason, requests.c.version,
    ).cte('stopped')
    op.execute(events.insert().from_select(['request_id', 'conversation_id', 'kind', 'payload'], sa.select(
        stopped.c.id, stopped.c.conversation_id, sa.literal('terminal'),
        sa.func.jsonb_build_object('state', stopped.c.state, 'reason', stopped.c.reason, 'version', stopped.c.version),
    )))
    messages = sa.table('messages', sa.column('request_id', pg.UUID()),
                        sa.column('role', sa.Text()), sa.column('excluded', sa.Boolean()))
    op.execute(messages.update().where(
        messages.c.role == 'assistant',
        messages.c.request_id.in_(sa.select(requests.c.id).where(requests.c.reason == 'session_binding_missing')),
    ).values(excluded=True))
    op.create_check_constraint('unfinished_session_required', 'requests',
                               "origin_session IS NOT NULL OR state IN ('completed','interrupted','failed')")
    op.create_table(
        'email_verifications',
        sa.Column('token_hash', sa.Text(), nullable=False),
        sa.Column('owner_id', pg.UUID(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint('token_hash', name='email_verifications_pkey'),
        sa.ForeignKeyConstraint(['owner_id'], ['accounts.id'], name='email_verifications_owner_id_fkey'),
    )
    op.create_table(
        'account_invitations',
        sa.Column('token_hash', sa.Text(), nullable=False),
        sa.Column('email', sa.Text(), nullable=False),
        sa.Column('role', sa.Text(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint('token_hash', name='account_invitations_pkey'),
        sa.CheckConstraint("role='super_admin'", name='account_invitations_role_check'),
    )
    op.create_table(
        'accounts_audit',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('actor_id', pg.UUID()),
        sa.Column('target_id', pg.UUID(), nullable=False),
        sa.Column('action', sa.Text(), nullable=False),
        sa.Column('previous', pg.JSONB(), nullable=False),
        sa.Column('updated', pg.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id', name='accounts_audit_pkey'),
        sa.ForeignKeyConstraint(['actor_id'], ['accounts.id'], name='accounts_audit_actor_id_fkey'),
        sa.ForeignKeyConstraint(['target_id'], ['accounts.id'], name='accounts_audit_target_id_fkey'),
    )


def downgrade():
    raise RuntimeError('Destructive accounts baseline downgrade is unsupported')
