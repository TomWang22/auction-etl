ALTER TABLE account.auction_listing
    DROP CONSTRAINT account_auction_listing_marketplace_check,
    ADD CONSTRAINT account_auction_listing_marketplace_check
        CHECK (
            marketplace IN (
                'buyee',
                'ebay',
                'gripsweat',
                'yahoo_auction',
                'yahoo_fleamarket'
            )
        );

ALTER TABLE account.artist_marketplace
    DROP CONSTRAINT artist_marketplace_check,
    ADD CONSTRAINT artist_marketplace_check
        CHECK (
            marketplace IN (
                'ebay',
                'buyee',
                'gripsweat',
                'yahoo_auction',
                'yahoo_fleamarket'
            )
        );

ALTER TABLE account.marketplace_connection
    DROP CONSTRAINT marketplace_connection_marketplace_check,
    ADD CONSTRAINT marketplace_connection_marketplace_check
        CHECK (
            marketplace IN (
                'buyee',
                'ebay',
                'gripsweat',
                'yahoo_auction',
                'yahoo_fleamarket'
            )
        );

ALTER TABLE ops.refresh_marketplace
    DROP CONSTRAINT refresh_marketplace_name_check,
    ADD CONSTRAINT refresh_marketplace_name_check
        CHECK (
            marketplace IN (
                'buyee',
                'ebay',
                'gripsweat',
                'yahoo_auction',
                'yahoo_fleamarket'
            )
        );

ALTER TABLE ops.refresh_event
    DROP CONSTRAINT refresh_event_marketplace_check,
    ADD CONSTRAINT refresh_event_marketplace_check
        CHECK (
            marketplace IS NULL
            OR marketplace IN (
                'buyee',
                'ebay',
                'gripsweat',
                'yahoo_auction',
                'yahoo_fleamarket'
            )
        );
