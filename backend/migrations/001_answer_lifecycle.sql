CREATE TABLE accounts (
    id uuid PRIMARY KEY,
    role text NOT NULL CHECK (role IN ('user','admin','super_admin')),
    verified boolean NOT NULL DEFAULT false,
    active boolean NOT NULL DEFAULT true,
    disabled boolean NOT NULL DEFAULT false,
    paid boolean NOT NULL DEFAULT false,
    context_epoch bigint NOT NULL DEFAULT 0
);
CREATE TABLE sessions (
    token_hash text PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES accounts(id),
    expires_at timestamptz NOT NULL,
    revoked boolean NOT NULL DEFAULT false
);
CREATE TABLE conversations (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES accounts(id),
    context_epoch bigint NOT NULL DEFAULT 0,
    UNIQUE(id, owner_id)
);
CREATE TABLE documents (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES accounts(id),
    ready boolean NOT NULL DEFAULT false,
    deleted boolean NOT NULL DEFAULT false
);
CREATE TABLE tabs (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES accounts(id),
    proof_hash text NOT NULL,
    connection_epoch bigint NOT NULL DEFAULT 0,
    deadline timestamptz,
    UNIQUE(id, owner_id)
);
CREATE TABLE service_state (
    id integer PRIMARY KEY CHECK (id=1),
    epoch bigint NOT NULL DEFAULT 0,
    healthy_until timestamptz NOT NULL DEFAULT '-infinity'
);
INSERT INTO service_state(id) VALUES (1);
CREATE TABLE settings (
    id integer PRIMARY KEY CHECK (id=1),
    overrides jsonb NOT NULL DEFAULT '{}',
    revision bigint NOT NULL DEFAULT 0,
    applied_revision bigint NOT NULL DEFAULT 0
);
INSERT INTO settings(id) VALUES (1);
CREATE TABLE settings_audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    actor_id uuid NOT NULL REFERENCES accounts(id),
    previous jsonb NOT NULL,
    updated jsonb NOT NULL,
    revision bigint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE requests (
    id uuid PRIMARY KEY,
    conversation_id uuid NOT NULL,
    owner_id uuid NOT NULL,
    operation_key uuid NOT NULL,
    fingerprint text NOT NULL,
    scope uuid[] NOT NULL,
    origin_tab uuid NOT NULL,
    state text NOT NULL CHECK (state IN ('accepted','searching','queued','generating','completed','interrupted','failed')),
    reason text,
    execution_epoch bigint NOT NULL,
    context_epoch bigint NOT NULL,
    version bigint NOT NULL DEFAULT 1,
    answer_text text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY(conversation_id,owner_id) REFERENCES conversations(id,owner_id),
    FOREIGN KEY(origin_tab,owner_id) REFERENCES tabs(id,owner_id),
    UNIQUE(owner_id,operation_key),
    UNIQUE(id,conversation_id)
);
CREATE UNIQUE INDEX one_unfinished_request ON requests(conversation_id)
WHERE state IN ('accepted','searching','queued','generating');
CREATE TABLE messages (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id uuid NOT NULL,
    conversation_id uuid NOT NULL,
    role text NOT NULL CHECK (role IN ('user','assistant')),
    text text NOT NULL,
    excluded boolean NOT NULL DEFAULT false,
    source_flags jsonb NOT NULL DEFAULT '{}',
    FOREIGN KEY(request_id,conversation_id) REFERENCES requests(id,conversation_id),
    UNIQUE(request_id,role)
);
CREATE TABLE events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id uuid NOT NULL,
    conversation_id uuid NOT NULL,
    kind text NOT NULL,
    payload jsonb NOT NULL,
    FOREIGN KEY(request_id,conversation_id) REFERENCES requests(id,conversation_id)
);
CREATE INDEX events_conversation_cursor ON events(conversation_id,id);
CREATE INDEX messages_conversation_order ON messages(conversation_id,id);
CREATE INDEX requests_conversation_order ON requests(conversation_id,created_at,id);
