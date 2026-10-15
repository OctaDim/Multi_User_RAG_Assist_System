ALTER TABLE tabs ADD COLUMN connected boolean NOT NULL DEFAULT false;
ALTER TABLE tabs ADD COLUMN confirmed boolean NOT NULL DEFAULT false;
ALTER TABLE tabs ADD COLUMN ack_until timestamptz;
ALTER TABLE tabs ADD COLUMN challenge_hash text;
CREATE INDEX tabs_presence_due ON tabs(ack_until,deadline);
