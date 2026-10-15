ALTER TABLE accounts ADD COLUMN email text UNIQUE;
ALTER TABLE accounts ADD COLUMN password_hash text;
ALTER TABLE accounts ADD CONSTRAINT account_credentials_pair CHECK ((email IS NULL) = (password_hash IS NULL));
ALTER TABLE sessions ADD COLUMN id uuid NOT NULL DEFAULT gen_random_uuid();
ALTER TABLE sessions ADD CONSTRAINT session_identity UNIQUE(id,owner_id);
ALTER TABLE requests ADD COLUMN origin_session uuid;
ALTER TABLE requests ADD CONSTRAINT request_session_owner FOREIGN KEY(origin_session,owner_id) REFERENCES sessions(id,owner_id);
-- Existing admissions have no provable originating session. Preserve history and fence them.
WITH stopped AS (
    UPDATE requests SET state='interrupted',reason='session_binding_missing',version=version+1
    WHERE state IN ('accepted','searching','queued','generating') RETURNING *
)
INSERT INTO events(request_id,conversation_id,kind,payload)
SELECT id,conversation_id,'terminal',jsonb_build_object('state',state,'reason',reason,'version',version) FROM stopped;
UPDATE messages SET excluded=true WHERE role='assistant' AND request_id IN
    (SELECT id FROM requests WHERE reason='session_binding_missing');
ALTER TABLE requests ADD CONSTRAINT unfinished_session_required CHECK
    (origin_session IS NOT NULL OR state IN ('completed','interrupted','failed'));
CREATE TABLE email_verifications (
    token_hash text PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES accounts(id),
    expires_at timestamptz NOT NULL,
    consumed boolean NOT NULL DEFAULT false
);
CREATE TABLE account_invitations (
    token_hash text PRIMARY KEY,
    email text NOT NULL,
    role text NOT NULL CHECK(role='super_admin'),
    expires_at timestamptz NOT NULL,
    consumed boolean NOT NULL DEFAULT false
);
CREATE TABLE accounts_audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_id uuid REFERENCES accounts(id),
    target_id uuid NOT NULL REFERENCES accounts(id),
    action text NOT NULL,
    previous jsonb NOT NULL,
    updated jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
