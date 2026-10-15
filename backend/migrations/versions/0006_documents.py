"""Add document ingestion and policy history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = '0006_documents'
down_revision = '0005_accounts'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'document_policies',
        sa.Column('owner_id', pg.UUID(), nullable=False),
        sa.Column('limits', pg.JSONB(), nullable=False),
        sa.Column('permissions', pg.JSONB(), nullable=False),
        sa.Column('handwriting_epoch', sa.BigInteger(), nullable=False, server_default=sa.text('0')),
        sa.PrimaryKeyConstraint('owner_id', name='document_policies_pkey'),
        sa.ForeignKeyConstraint(['owner_id'], ['accounts.id'], name='document_policies_owner_id_fkey'),
    )
    op.create_table(
        'document_files',
        sa.Column('document_id', pg.UUID(), nullable=False),
        sa.Column('batch_id', pg.UUID(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('format', sa.Text(), nullable=False),
        sa.Column('declared_bytes', sa.BigInteger(), nullable=False),
        sa.Column('original_sha256', sa.Text()),
        sa.Column('state', sa.Text(), nullable=False),
        sa.Column('admitted_limits', pg.JSONB(), nullable=False),
        sa.Column('admitted_handwriting_epoch', sa.BigInteger(), nullable=False, server_default=sa.text('0')),
        sa.Column('mode', sa.Text(), nullable=False, server_default='complete'),
        sa.Column('error', sa.Text()),
        sa.Column('failure_page', sa.Integer()),
        sa.Column('job_id', pg.UUID()),
        sa.Column('correction_pages', pg.JSONB()),
        sa.Column('correction_base', pg.UUID()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.PrimaryKeyConstraint('document_id', name='document_files_pkey'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name='document_files_document_id_fkey'),
        sa.ForeignKeyConstraint(['correction_base'], ['source_revisions.id'], name='document_files_correction_base_fkey'),
        sa.CheckConstraint("format IN ('pdf','docx','txt','md')", name='document_files_format_check'),
        sa.CheckConstraint('declared_bytes>0', name='document_files_declared_bytes_check'),
        sa.CheckConstraint("state IN ('receiving','queued','processing','awaiting_choice','ready','failed','cancelled')", name='document_files_state_check'),
        sa.CheckConstraint("mode IN ('complete','skip_handwriting')", name='document_files_mode_check'),
    )
    op.create_index('document_files_jobs', 'document_files', ['state', 'created_at'])
    op.create_table(
        'document_page_texts',
        sa.Column('revision_id', pg.UUID(), nullable=False),
        sa.Column('page', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('regions', pg.JSONB(), nullable=False, server_default='[]'),
        sa.PrimaryKeyConstraint('revision_id', 'page', name='document_page_texts_pkey'),
        sa.ForeignKeyConstraint(['revision_id', 'page'], ['source_pages.revision_id', 'source_pages.page'], name='document_page_texts_revision_id_page_fkey'),
    )
    op.execute('''CREATE TRIGGER immutable_page_texts BEFORE INSERT OR UPDATE OR DELETE ON document_page_texts
FOR EACH ROW EXECUTE FUNCTION protect_published_revision()''')
    op.create_table(
        'document_policy_audit',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column('actor_id', pg.UUID(), nullable=False),
        sa.Column('target_id', pg.UUID(), nullable=False),
        sa.Column('previous', pg.JSONB(), nullable=False),
        sa.Column('updated', pg.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.PrimaryKeyConstraint('id', name='document_policy_audit_pkey'),
        sa.ForeignKeyConstraint(['actor_id'], ['accounts.id'], name='document_policy_audit_actor_id_fkey'),
        sa.ForeignKeyConstraint(['target_id'], ['accounts.id'], name='document_policy_audit_target_id_fkey'),
    )


def downgrade():
    raise RuntimeError('Destructive documents baseline downgrade is unsupported')
