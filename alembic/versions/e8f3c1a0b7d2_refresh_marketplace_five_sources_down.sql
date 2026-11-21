-- Restore three-marketplace ordinal ceiling only when no ordinal > 3 rows remain.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM ops.refresh_marketplace
        WHERE ordinal > 3
    ) THEN
        RAISE EXCEPTION
            'Cannot downgrade refresh_marketplace ordinal check while ordinal > 3 rows exist';
    END IF;
END $$;

ALTER TABLE ops.refresh_marketplace
    DROP CONSTRAINT refresh_marketplace_ordinal_check,
    ADD CONSTRAINT refresh_marketplace_ordinal_check
        CHECK (ordinal BETWEEN 1 AND 3);

ALTER TABLE ops.refresh_marketplace
    DROP CONSTRAINT refresh_marketplace_state_check,
    ADD CONSTRAINT refresh_marketplace_state_check
        CHECK (
            state IN (
                'waiting',
                'running',
                'done',
                'failed',
                'skipped',
                'authentication_required',
                'awaiting_handoff'
            )
        );
