ALTER TABLE ops.refresh_marketplace
    ADD COLUMN visible_count integer NOT NULL DEFAULT 0,
    ADD COLUMN visible_added integer NOT NULL DEFAULT 0;

ALTER TABLE ops.refresh_marketplace
    ADD CONSTRAINT refresh_marketplace_visible_count_nonnegative
        CHECK (visible_count >= 0),
    ADD CONSTRAINT refresh_marketplace_visible_added_nonnegative
        CHECK (visible_added >= 0);

CREATE TABLE ops.refresh_job_input (
    job_id uuid NOT NULL
        REFERENCES ops.refresh_job(id)
        ON DELETE CASCADE,
    marketplace text NOT NULL,
    schema_version text NOT NULL,
    sha256 char(64) NOT NULL,
    byte_length integer NOT NULL,
    source_name text NOT NULL,
    collector_url text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, marketplace),
    CONSTRAINT refresh_job_input_marketplace_check
        CHECK (marketplace = 'ebay'),
    CONSTRAINT refresh_job_input_sha256_check
        CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT refresh_job_input_byte_length_check
        CHECK (byte_length > 0 AND byte_length <= 393216),
    CONSTRAINT refresh_job_input_collector_url_check
        CHECK (collector_url LIKE 'collector://ebay/%')
);

CREATE INDEX refresh_job_input_sha256_idx
    ON ops.refresh_job_input (sha256);
