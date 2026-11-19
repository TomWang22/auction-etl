DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM account.auction_listing
        WHERE marketplace IN ('yahoo_auction', 'yahoo_fleamarket')
    ) OR EXISTS (
        SELECT 1
        FROM account.artist_marketplace
        WHERE marketplace IN ('yahoo_auction', 'yahoo_fleamarket')
    ) OR EXISTS (
        SELECT 1
        FROM warehouse.auction
        WHERE marketplace IN ('yahoo_auction', 'yahoo_fleamarket')
    ) THEN
        RAISE EXCEPTION
            'Cannot downgrade yahoo JP marketplace checks while yahoo_* rows exist';
    END IF;
END $$;

ALTER TABLE account.auction_listing
    DROP CONSTRAINT account_auction_listing_marketplace_check,
    ADD CONSTRAINT account_auction_listing_marketplace_check
        CHECK (marketplace IN ('buyee', 'ebay', 'gripsweat'));

ALTER TABLE account.artist_marketplace
    DROP CONSTRAINT artist_marketplace_check,
    ADD CONSTRAINT artist_marketplace_check
        CHECK (marketplace IN ('ebay', 'buyee', 'gripsweat'));

ALTER TABLE account.marketplace_connection
    DROP CONSTRAINT marketplace_connection_marketplace_check,
    ADD CONSTRAINT marketplace_connection_marketplace_check
        CHECK (marketplace IN ('buyee', 'ebay', 'gripsweat'));

ALTER TABLE ops.refresh_marketplace
    DROP CONSTRAINT refresh_marketplace_name_check,
    ADD CONSTRAINT refresh_marketplace_name_check
        CHECK (marketplace IN ('buyee', 'ebay', 'gripsweat'));

ALTER TABLE ops.refresh_event
    DROP CONSTRAINT refresh_event_marketplace_check,
    ADD CONSTRAINT refresh_event_marketplace_check
        CHECK (
            marketplace IS NULL
            OR marketplace IN ('buyee', 'ebay', 'gripsweat')
        );
