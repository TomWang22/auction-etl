DO $phase_d$
BEGIN
    IF to_regclass('identity.account') IS NULL THEN
        RAISE EXCEPTION
            'Phase-D identity.account foundation is missing';
    END IF;

    IF to_regclass('identity.app_user') IS NULL THEN
        RAISE EXCEPTION
            'Phase-D identity.app_user foundation is missing';
    END IF;

    IF to_regclass('account.auction_listing') IS NULL THEN
        RAISE EXCEPTION
            'Phase-D account.auction_listing foundation is missing';
    END IF;

    IF to_regclass('ops.refresh_job') IS NULL THEN
        RAISE EXCEPTION
            'ops.refresh_job is missing';
    END IF;

    IF to_regclass('warehouse.auction_collector') IS NULL THEN
        RAISE EXCEPTION
            'warehouse.auction_collector is missing';
    END IF;
END
$phase_d$;

ALTER TABLE ops.refresh_job
    ADD COLUMN IF NOT EXISTS account_id uuid;

ALTER TABLE ops.refresh_job
    ADD COLUMN IF NOT EXISTS requested_by_user_id uuid;

ALTER TABLE warehouse.auction_collector
    ADD COLUMN IF NOT EXISTS account_id uuid;

DO $phase_d$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'ops.refresh_job'::regclass
          AND conname = 'refresh_job_account_fk'
    ) THEN
        ALTER TABLE ops.refresh_job
            ADD CONSTRAINT refresh_job_account_fk
            FOREIGN KEY (account_id)
            REFERENCES identity.account(id)
            ON DELETE RESTRICT
            NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'ops.refresh_job'::regclass
          AND conname = 'refresh_job_requested_by_user_fk'
    ) THEN
        ALTER TABLE ops.refresh_job
            ADD CONSTRAINT refresh_job_requested_by_user_fk
            FOREIGN KEY (requested_by_user_id)
            REFERENCES identity.app_user(id)
            ON DELETE SET NULL
            NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'warehouse.auction_collector'::regclass
          AND conname = 'auction_collector_account_fk'
    ) THEN
        ALTER TABLE warehouse.auction_collector
            ADD CONSTRAINT auction_collector_account_fk
            FOREIGN KEY (account_id)
            REFERENCES identity.account(id)
            ON DELETE RESTRICT
            NOT VALID;
    END IF;
END
$phase_d$;

ALTER TABLE ops.refresh_job
    VALIDATE CONSTRAINT refresh_job_account_fk;

ALTER TABLE ops.refresh_job
    VALIDATE CONSTRAINT refresh_job_requested_by_user_fk;

ALTER TABLE warehouse.auction_collector
    VALIDATE CONSTRAINT auction_collector_account_fk;

DROP INDEX IF EXISTS ops.refresh_job_single_active_idx;

CREATE UNIQUE INDEX IF NOT EXISTS
    refresh_job_one_active_per_account_idx
ON ops.refresh_job (account_id)
WHERE
    account_id IS NOT NULL
    AND state IN ('queued', 'running');

CREATE UNIQUE INDEX IF NOT EXISTS
    refresh_job_one_legacy_active_idx
ON ops.refresh_job ((1))
WHERE
    account_id IS NULL
    AND state IN ('queued', 'running');

CREATE INDEX IF NOT EXISTS
    refresh_job_account_requested_idx
ON ops.refresh_job (
    account_id,
    requested_at DESC,
    created_at DESC,
    id
);

CREATE INDEX IF NOT EXISTS
    refresh_job_account_state_idx
ON ops.refresh_job (
    account_id,
    state,
    requested_at DESC,
    id
);

DO $phase_d$
DECLARE
    constraint_name text;
    index_name text;
    inbound_fk_count bigint;
BEGIN
    SELECT COUNT(*)
    INTO inbound_fk_count
    FROM pg_constraint
    WHERE contype = 'f'
      AND confrelid =
          'warehouse.auction_collector'::regclass;

    IF inbound_fk_count > 0 THEN
        RAISE EXCEPTION
            'Unsafe Phase D transition: warehouse.auction_collector '
            'has % inbound foreign key constraint(s)',
            inbound_fk_count;
    END IF;

    FOR constraint_name IN
        SELECT c.conname
        FROM pg_constraint AS c
        WHERE c.conrelid =
                  'warehouse.auction_collector'::regclass
          AND c.contype IN ('p', 'u')
          AND pg_get_constraintdef(c.oid) ~*
              '^(PRIMARY KEY|UNIQUE) \(marketplace, listing_id\)$'
    LOOP
        EXECUTE format(
            'ALTER TABLE warehouse.auction_collector '
            'DROP CONSTRAINT %I',
            constraint_name
        );
    END LOOP;

    FOR index_name IN
        SELECT index_relation.relname
        FROM pg_index AS index_row
        JOIN pg_class AS index_relation
          ON index_relation.oid =
             index_row.indexrelid
        LEFT JOIN pg_constraint AS owning_constraint
          ON owning_constraint.conindid =
             index_relation.oid
        WHERE index_row.indrelid =
                  'warehouse.auction_collector'::regclass
          AND index_row.indisunique
          AND NOT index_row.indisprimary
          AND owning_constraint.oid IS NULL
          AND pg_get_indexdef(index_relation.oid) ~*
              '\(marketplace, listing_id\)'
          AND pg_get_indexdef(index_relation.oid)
              NOT ILIKE '%account_id%'
    LOOP
        EXECUTE format(
            'DROP INDEX IF EXISTS warehouse.%I',
            index_name
        );
    END LOOP;
END
$phase_d$;

CREATE UNIQUE INDEX IF NOT EXISTS
    auction_collector_legacy_listing_uidx
ON warehouse.auction_collector (
    marketplace,
    listing_id
)
WHERE account_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS
    auction_collector_account_listing_uidx
ON warehouse.auction_collector (
    account_id,
    marketplace,
    listing_id
)
WHERE account_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS
    auction_collector_account_lookup_idx
ON warehouse.auction_collector (
    account_id,
    marketplace,
    listing_id
);

CREATE INDEX IF NOT EXISTS
    auction_listing_account_first_seen_idx
ON account.auction_listing (
    account_id,
    first_seen_at DESC,
    marketplace,
    listing_id
);

COMMENT ON INDEX ops.refresh_job_one_active_per_account_idx IS
    'Phase D: at most one queued/running durable refresh per owned account';

COMMENT ON INDEX ops.refresh_job_one_legacy_active_idx IS
    'Phase D compatibility: at most one unowned legacy active refresh globally';

COMMENT ON INDEX warehouse.auction_collector_account_listing_uidx IS
    'Phase D: collector metadata identity is private per account';
