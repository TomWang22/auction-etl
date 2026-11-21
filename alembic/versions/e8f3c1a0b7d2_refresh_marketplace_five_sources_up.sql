-- Allow five planned marketplaces (Buyee, eBay, Gripsweat, Yahoo Auctions, Yahoo フリマ).
ALTER TABLE ops.refresh_marketplace
    DROP CONSTRAINT refresh_marketplace_ordinal_check,
    ADD CONSTRAINT refresh_marketplace_ordinal_check
        CHECK (ordinal BETWEEN 1 AND 5);

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
                'rate_limited',
                'authentication_required',
                'awaiting_handoff'
            )
        );
