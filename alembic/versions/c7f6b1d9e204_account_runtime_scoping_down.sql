DO $phase_d$
DECLARE
    active_count bigint;
    duplicate_key_groups bigint;
BEGIN
    SELECT COUNT(*)
    INTO active_count
    FROM ops.refresh_job
    WHERE state IN ('queued', 'running');

    IF active_count > 1 THEN
        RAISE EXCEPTION
            'Unsafe downgrade: more than one active refresh job exists';
    END IF;

    SELECT COUNT(*)
    INTO duplicate_key_groups
    FROM (
        SELECT
            marketplace,
            listing_id
        FROM warehouse.auction_collector
        GROUP BY
            marketplace,
            listing_id
        HAVING COUNT(*) > 1
    ) AS duplicate_keys;

    IF duplicate_key_groups > 0 THEN
        RAISE EXCEPTION
            'Unsafe downgrade: % auction_collector marketplace/listing '
            'key group(s) exist across multiple account rows',
            duplicate_key_groups;
    END IF;
END
$phase_d$;

DO $phase_d$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid =
                  'warehouse.auction_collector'::regclass
          AND contype = 'p'
          AND pg_get_constraintdef(oid) ~*
              '^PRIMARY KEY \(marketplace, listing_id\)$'
    ) THEN
        ALTER TABLE warehouse.auction_collector
            ADD CONSTRAINT auction_collector_pkey
            PRIMARY KEY (
                marketplace,
                listing_id
            );
    END IF;
END
$phase_d$;

DROP INDEX IF EXISTS
    account.auction_listing_account_first_seen_idx;

DROP INDEX IF EXISTS
    account.auction_listing_account_first_visible_idx;

DROP INDEX IF EXISTS
    warehouse.auction_collector_account_lookup_idx;

DROP INDEX IF EXISTS
    warehouse.auction_collector_account_listing_uidx;

DROP INDEX IF EXISTS
    warehouse.auction_collector_legacy_listing_uidx;

DROP INDEX IF EXISTS
    ops.refresh_job_account_state_idx;

DROP INDEX IF EXISTS
    ops.refresh_job_account_requested_idx;

DROP INDEX IF EXISTS
    ops.refresh_job_one_legacy_active_idx;

DROP INDEX IF EXISTS
    ops.refresh_job_one_active_per_account_idx;

CREATE UNIQUE INDEX IF NOT EXISTS
    refresh_job_single_active_idx
ON ops.refresh_job ((1))
WHERE state IN ('queued', 'running');

-- Nullable ownership columns belong to the Phase-D foundation/cutover path.
-- They are intentionally preserved by this compatibility downgrade.
