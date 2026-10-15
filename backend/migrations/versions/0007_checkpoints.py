"""Adopt the stock langgraph-checkpoint-postgres 3.1.3 schema (steps 0–9)."""
from alembic import context, op

revision = '0007_checkpoints'
down_revision = '0006_documents'
branch_labels = None
depends_on = None


def upgrade():
    context.config.attributes['schema_contract'].upgrade_checkpoints(op.get_bind())


def downgrade():
    raise RuntimeError('Destructive checkpoint baseline downgrade is unsupported')
