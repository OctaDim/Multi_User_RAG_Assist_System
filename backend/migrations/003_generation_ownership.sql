ALTER TABLE service_state ADD COLUMN runtime_id uuid NOT NULL DEFAULT gen_random_uuid();
ALTER TABLE service_state ADD COLUMN physical_host text;
CREATE TABLE coordinator_lease (
    id integer PRIMARY KEY CHECK (id=1),
    epoch bigint NOT NULL,
    healthy_until timestamptz NOT NULL
);
INSERT INTO coordinator_lease SELECT id,epoch,healthy_until FROM service_state;
ALTER TABLE service_state DROP COLUMN healthy_until;
