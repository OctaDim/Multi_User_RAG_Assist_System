"""Dialog dates and deletion state; existing unknown dates remain unknown."""
from alembic import op
import sqlalchemy as sa

revision = '0008_dialog_metadata'
down_revision = '0007_checkpoints'
branch_labels = None
depends_on = None


def upgrade():
    for name in ('created_at', 'updated_at', 'deleted_at'):
        op.add_column('conversations', sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    for name in ('created_at', 'updated_at'):
        op.alter_column('conversations', name, server_default=sa.text('clock_timestamp()'))


def downgrade():
    raise RuntimeError('Destructive dialog metadata downgrade is unsupported')
