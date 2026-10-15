"""Add published sources, provenance and graph bindings."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg
from pgvector.sqlalchemy import VECTOR

revision = '0002_sources_and_context'
down_revision = '0001_answer_lifecycle'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.create_table(
        'source_revisions',
        sa.Column('id', pg.UUID(), nullable=False),
        sa.Column('document_id', pg.UUID(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('upload_complete', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('page_count', sa.Integer(), nullable=False),
        sa.Column('mode', sa.Text(), nullable=False),
        sa.Column('skip_confirmed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('limitations', pg.JSONB(), nullable=False, server_default='[]'),
        sa.PrimaryKeyConstraint('id', name='source_revisions_pkey'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name='source_revisions_document_id_fkey'),
        sa.CheckConstraint("status IN ('staging','published','failed','cancelled')", name='source_revisions_status_check'),
        sa.CheckConstraint('page_count>0', name='source_revisions_page_count_check'),
        sa.CheckConstraint("mode IN ('complete','skip_handwriting')", name='source_revisions_mode_check'),
        sa.CheckConstraint("jsonb_typeof(limitations)='array'", name='source_revisions_limitations_check'),
        sa.UniqueConstraint('document_id', 'id', name='source_revisions_document_id_id_key'),
    )
    op.add_column('documents', sa.Column('published_revision', pg.UUID()))
    op.create_foreign_key('documents_id_published_revision_fkey', 'documents', 'source_revisions',
                          ['id', 'published_revision'], ['document_id', 'id'])
    op.create_table(
        'source_pages',
        sa.Column('revision_id', pg.UUID(), nullable=False),
        sa.Column('page', sa.Integer(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('revision_id', 'page', name='source_pages_pkey'),
        sa.ForeignKeyConstraint(['revision_id'], ['source_revisions.id'], name='source_pages_revision_id_fkey'),
        sa.CheckConstraint('page>0', name='source_pages_page_check'),
        sa.CheckConstraint("status IN ('ready','failed','processing')", name='source_pages_status_check'),
    )
    op.create_table(
        'source_chunks',
        sa.Column('id', pg.UUID(), nullable=False),
        sa.Column('revision_id', pg.UUID(), nullable=False),
        sa.Column('page', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('span_start', sa.Integer(), nullable=False),
        sa.Column('span_end', sa.Integer(), nullable=False),
        sa.Column('coordinates', pg.JSONB(), nullable=False, server_default='{}'),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('embedding', VECTOR(384), nullable=False),
        sa.PrimaryKeyConstraint('id', name='source_chunks_pkey'),
        sa.CheckConstraint('span_start>=0', name='source_chunks_span_start_check'),
        sa.CheckConstraint("kind IN ('printed','handwritten','skip')", name='source_chunks_kind_check'),
        sa.CheckConstraint('span_end=span_start+char_length(text)', name='source_chunks_check'),
        sa.ForeignKeyConstraint(['revision_id', 'page'], ['source_pages.revision_id', 'source_pages.page'], name='source_chunks_revision_id_page_fkey'),
    )
    op.create_index('source_chunks_revision', 'source_chunks', ['revision_id'])
    op.execute("""CREATE VIEW available_source_revisions AS
SELECT d.id AS document_id,d.owner_id,r.id AS revision_id,r.mode,r.limitations
FROM documents d JOIN source_revisions r ON r.id=d.published_revision AND r.document_id=d.id
WHERE d.ready AND NOT d.deleted AND r.status='published' AND r.upload_complete
  AND (r.mode='complete' OR (r.skip_confirmed AND jsonb_array_length(r.limitations)>0))
  AND (SELECT count(*) FROM source_pages p WHERE p.revision_id=r.id)=r.page_count
  AND NOT EXISTS (SELECT 1 FROM source_pages p WHERE p.revision_id=r.id AND (p.status<>'ready' OR p.page>r.page_count))""")
    op.create_table(
        'request_sources',
        sa.Column('request_id', pg.UUID(), nullable=False),
        sa.Column('document_id', pg.UUID(), nullable=False),
        sa.Column('revision_id', pg.UUID(), nullable=False),
        sa.PrimaryKeyConstraint('request_id', 'document_id', 'revision_id', name='request_sources_pkey'),
        sa.ForeignKeyConstraint(['request_id'], ['requests.id'], name='request_sources_request_id_fkey'),
        sa.ForeignKeyConstraint(['document_id', 'revision_id'], ['source_revisions.document_id', 'source_revisions.id'], name='request_sources_document_id_revision_id_fkey'),
    )
    op.add_column('requests', sa.Column('passport', pg.JSONB(), nullable=False, server_default='{}'))
    op.create_table(
        'graph_bindings',
        sa.Column('request_id', pg.UUID(), nullable=False),
        sa.Column('thread_id', sa.Text(), nullable=False),
        sa.Column('owner_id', pg.UUID(), nullable=False),
        sa.Column('conversation_id', pg.UUID(), nullable=False),
        sa.Column('execution_epoch', sa.BigInteger(), nullable=False),
        sa.Column('context_epoch', sa.BigInteger(), nullable=False),
        sa.Column('account_epoch', sa.BigInteger(), nullable=False),
        sa.Column('started', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint('request_id', name='graph_bindings_pkey'),
        sa.UniqueConstraint('thread_id', name='graph_bindings_thread_id_key'),
        sa.ForeignKeyConstraint(['request_id'], ['requests.id'], name='graph_bindings_request_id_fkey'),
        sa.ForeignKeyConstraint(['owner_id'], ['accounts.id'], name='graph_bindings_owner_id_fkey'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name='graph_bindings_conversation_id_fkey'),
    )
    # Changing text under a published identity would evade provenance checks.
    op.execute("""CREATE FUNCTION protect_published_revision() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    previous_id uuid;
    next_id uuid;
    revision uuid;
BEGIN
    IF TG_OP<>'INSERT' THEN
        previous_id := (to_jsonb(OLD)->>CASE WHEN TG_TABLE_NAME='source_revisions' THEN 'id' ELSE 'revision_id' END)::uuid;
    END IF;
    IF TG_OP<>'DELETE' THEN
        next_id := (to_jsonb(NEW)->>CASE WHEN TG_TABLE_NAME='source_revisions' THEN 'id' ELSE 'revision_id' END)::uuid;
    END IF;
    FOR revision IN SELECT DISTINCT value FROM unnest(ARRAY[previous_id,next_id]) value WHERE value IS NOT NULL ORDER BY value LOOP
        PERFORM id FROM source_revisions WHERE id=revision FOR SHARE;
        IF EXISTS(SELECT 1 FROM documents WHERE published_revision=revision)
            OR EXISTS(SELECT 1 FROM request_sources WHERE revision_id=revision) THEN
            RAISE EXCEPTION 'Published source revision is immutable; create a new revision' USING ERRCODE='55000';
        END IF;
    END LOOP;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$""")
    op.execute('CREATE TRIGGER immutable_revision BEFORE UPDATE OR DELETE ON source_revisions FOR EACH ROW EXECUTE FUNCTION protect_published_revision()')
    op.execute('CREATE TRIGGER immutable_pages BEFORE INSERT OR UPDATE OR DELETE ON source_pages FOR EACH ROW EXECUTE FUNCTION protect_published_revision()')
    op.execute('CREATE TRIGGER immutable_chunks BEFORE INSERT OR UPDATE OR DELETE ON source_chunks FOR EACH ROW EXECUTE FUNCTION protect_published_revision()')


def downgrade():
    raise RuntimeError('Destructive sources and context baseline downgrade is unsupported')
