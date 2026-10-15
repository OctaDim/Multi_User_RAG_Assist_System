"""Track connected tabs and acknowledgement deadlines."""
from alembic import op
import sqlalchemy as sa

revision = '0004_tab_presence'
down_revision = '0003_generation_ownership'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tabs', sa.Column('connected', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('tabs', sa.Column('confirmed', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('tabs', sa.Column('ack_until', sa.DateTime(timezone=True)))
    op.add_column('tabs', sa.Column('challenge_hash', sa.Text()))
    op.create_index('tabs_presence_due', 'tabs', ['ack_until', 'deadline'])


def downgrade():
    raise RuntimeError('Destructive tab presence baseline downgrade is unsupported')
