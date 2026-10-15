"""Separate coordinator lease from process ownership."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = '0003_generation_ownership'
down_revision = '0002_sources_and_context'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('service_state', sa.Column('runtime_id', pg.UUID(), nullable=False, server_default=sa.func.gen_random_uuid()))
    op.add_column('service_state', sa.Column('physical_host', sa.Text()))
    lease = op.create_table(
        'coordinator_lease',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=False),
        sa.Column('epoch', sa.BigInteger(), nullable=False),
        sa.Column('healthy_until', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name='coordinator_lease_pkey'),
        sa.CheckConstraint('id=1', name='coordinator_lease_id_check'),
    )
    state = sa.table('service_state', sa.column('id', sa.Integer()),
                     sa.column('epoch', sa.BigInteger()), sa.column('healthy_until', sa.DateTime(timezone=True)))
    op.execute(lease.insert().from_select(['id', 'epoch', 'healthy_until'], sa.select(state)))
    op.drop_column('service_state', 'healthy_until')


def downgrade():
    raise RuntimeError('Destructive generation ownership baseline downgrade is unsupported')
