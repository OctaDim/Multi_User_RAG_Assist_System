CREATE TABLE document_policies (
    owner_id uuid PRIMARY KEY REFERENCES accounts(id),
    limits jsonb NOT NULL,
    permissions jsonb NOT NULL,
    handwriting_epoch bigint NOT NULL DEFAULT 0
);
CREATE TABLE document_files (
    document_id uuid PRIMARY KEY REFERENCES documents(id),
    batch_id uuid NOT NULL,
    name text NOT NULL,
    format text NOT NULL CHECK(format IN ('pdf','docx','txt','md')),
    declared_bytes bigint NOT NULL CHECK(declared_bytes>0),
    original_sha256 text,
    state text NOT NULL CHECK(state IN ('receiving','queued','processing','awaiting_choice','ready','failed','cancelled')),
    admitted_limits jsonb NOT NULL,
    admitted_handwriting_epoch bigint NOT NULL DEFAULT 0,
    mode text NOT NULL DEFAULT 'complete' CHECK(mode IN ('complete','skip_handwriting')),
    error text,
    failure_page integer,
    job_id uuid,
    correction_pages jsonb,
    correction_base uuid REFERENCES source_revisions(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX document_files_jobs ON document_files(state,created_at);
CREATE TABLE document_page_texts (
    revision_id uuid NOT NULL,
    page integer NOT NULL,
    text text NOT NULL,
    regions jsonb NOT NULL DEFAULT '[]',
    PRIMARY KEY(revision_id,page),
    FOREIGN KEY(revision_id,page) REFERENCES source_pages(revision_id,page)
);
CREATE TRIGGER immutable_page_texts BEFORE INSERT OR UPDATE OR DELETE ON document_page_texts
FOR EACH ROW EXECUTE FUNCTION protect_published_revision();
CREATE TABLE document_policy_audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES accounts(id),
    target_id uuid NOT NULL REFERENCES accounts(id),
    previous jsonb NOT NULL,
    updated jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
