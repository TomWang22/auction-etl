DROP INDEX IF EXISTS ops.refresh_job_input_sha256_idx;
DROP TABLE IF EXISTS ops.refresh_job_input;

ALTER TABLE ops.refresh_marketplace
    DROP CONSTRAINT IF EXISTS refresh_marketplace_visible_added_nonnegative,
    DROP CONSTRAINT IF EXISTS refresh_marketplace_visible_count_nonnegative,
    DROP COLUMN IF EXISTS visible_added,
    DROP COLUMN IF EXISTS visible_count;
