CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE source_revisions (
    id uuid PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES documents(id),
    status text NOT NULL CHECK (status IN ('staging','published','failed','cancelled')),
    upload_complete boolean NOT NULL DEFAULT false,
    page_count integer NOT NULL CHECK (page_count>0),
    mode text NOT NULL CHECK (mode IN ('complete','skip_handwriting')),
    skip_confirmed boolean NOT NULL DEFAULT false,
    limitations jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(limitations)='array'),
    UNIQUE(document_id,id)
);
ALTER TABLE documents ADD COLUMN published_revision uuid;
ALTER TABLE documents ADD FOREIGN KEY(id,published_revision) REFERENCES source_revisions(document_id,id);
CREATE TABLE source_pages (
    revision_id uuid NOT NULL REFERENCES source_revisions(id),
    page integer NOT NULL CHECK (page>0),
    status text NOT NULL CHECK (status IN ('ready','failed','processing')),
    PRIMARY KEY(revision_id,page)
);
CREATE TABLE source_chunks (
    id uuid PRIMARY KEY,
    revision_id uuid NOT NULL,
    page integer NOT NULL,
    text text NOT NULL,
    span_start integer NOT NULL CHECK (span_start>=0),
    span_end integer NOT NULL,
    coordinates jsonb NOT NULL DEFAULT '{}',
    kind text NOT NULL CHECK (kind IN ('printed','handwritten','skip')),
    embedding vector(384) NOT NULL,
    CHECK (span_end=span_start+char_length(text)),
    FOREIGN KEY(revision_id,page) REFERENCES source_pages(revision_id,page)
);
CREATE INDEX source_chunks_revision ON source_chunks(revision_id);
CREATE VIEW available_source_revisions AS
SELECT d.id AS document_id,d.owner_id,r.id AS revision_id,r.mode,r.limitations
FROM documents d JOIN source_revisions r ON r.id=d.published_revision AND r.document_id=d.id
WHERE d.ready AND NOT d.deleted AND r.status='published' AND r.upload_complete
  AND (r.mode='complete' OR (r.skip_confirmed AND jsonb_array_length(r.limitations)>0))
  AND (SELECT count(*) FROM source_pages p WHERE p.revision_id=r.id)=r.page_count
  AND NOT EXISTS (SELECT 1 FROM source_pages p WHERE p.revision_id=r.id AND (p.status<>'ready' OR p.page>r.page_count));
CREATE TABLE request_sources (
    request_id uuid NOT NULL REFERENCES requests(id),
    document_id uuid NOT NULL,
    revision_id uuid NOT NULL,
    PRIMARY KEY(request_id,document_id,revision_id),
    FOREIGN KEY(document_id,revision_id) REFERENCES source_revisions(document_id,id)
);
ALTER TABLE requests ADD COLUMN passport jsonb NOT NULL DEFAULT '{}';
CREATE TABLE graph_bindings (
    request_id uuid PRIMARY KEY REFERENCES requests(id),
    thread_id text NOT NULL UNIQUE,
    owner_id uuid NOT NULL REFERENCES accounts(id),
    conversation_id uuid NOT NULL REFERENCES conversations(id),
    execution_epoch bigint NOT NULL,
    context_epoch bigint NOT NULL,
    account_epoch bigint NOT NULL,
    started boolean NOT NULL DEFAULT false
);

-- Changing text under a published identity would evade every provenance check.
CREATE FUNCTION protect_published_revision() RETURNS trigger LANGUAGE plpgsql AS $$
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
$$;
CREATE TRIGGER immutable_revision BEFORE UPDATE OR DELETE ON source_revisions FOR EACH ROW EXECUTE FUNCTION protect_published_revision();
CREATE TRIGGER immutable_pages BEFORE INSERT OR UPDATE OR DELETE ON source_pages FOR EACH ROW EXECUTE FUNCTION protect_published_revision();
CREATE TRIGGER immutable_chunks BEFORE INSERT OR UPDATE OR DELETE ON source_chunks FOR EACH ROW EXECUTE FUNCTION protect_published_revision();
