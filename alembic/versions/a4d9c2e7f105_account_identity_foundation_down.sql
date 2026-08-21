DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_class AS target_relation
        WHERE target_relation.oid = to_regclass('system.current_listing_completeness_alert')
          AND target_relation.relkind IN ('r', 'p')
    ) THEN
        ALTER TABLE system.current_listing_completeness_alert
            DROP COLUMN IF EXISTS account_id;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class AS target_relation
        WHERE target_relation.oid = to_regclass('system.listing_completeness_timeline')
          AND target_relation.relkind IN ('r', 'p')
    ) THEN
        ALTER TABLE system.listing_completeness_timeline
            DROP COLUMN IF EXISTS account_id;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class AS target_relation
        WHERE target_relation.oid = to_regclass('system.listing_completeness_snapshot')
          AND target_relation.relkind IN ('r', 'p')
    ) THEN
        ALTER TABLE system.listing_completeness_snapshot
            DROP COLUMN IF EXISTS account_id;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class AS target_relation
        WHERE target_relation.oid = to_regclass('system.auction_pressing_assignment_audit_event')
          AND target_relation.relkind IN ('r', 'p')
    ) THEN
        ALTER TABLE system.auction_pressing_assignment_audit_event
            DROP COLUMN IF EXISTS account_id;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class AS target_relation
        WHERE target_relation.oid = to_regclass('system.new_auction_assignment_queue')
          AND target_relation.relkind IN ('r', 'p')
    ) THEN
        ALTER TABLE system.new_auction_assignment_queue
            DROP COLUMN IF EXISTS account_id;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class AS target_relation
        WHERE target_relation.oid = to_regclass('warehouse.auction_pressing_assignment')
          AND target_relation.relkind IN ('r', 'p')
    ) THEN
        ALTER TABLE warehouse.auction_pressing_assignment
            DROP COLUMN IF EXISTS account_id;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class AS target_relation
        WHERE target_relation.oid = to_regclass('warehouse.auction_collector')
          AND target_relation.relkind IN ('r', 'p')
    ) THEN
        ALTER TABLE warehouse.auction_collector
            DROP COLUMN IF EXISTS account_id;
    END IF;
END
$$;

DROP INDEX IF EXISTS ops.refresh_job_account_created_idx;

ALTER TABLE ops.refresh_job
    DROP COLUMN IF EXISTS requested_by_user_id,
    DROP COLUMN IF EXISTS account_id;

DROP SCHEMA IF EXISTS account CASCADE;
DROP SCHEMA IF EXISTS identity CASCADE;
