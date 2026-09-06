ALTER TABLE account.artist_marketplace
    DROP CONSTRAINT artist_marketplace_check,
    ADD CONSTRAINT artist_marketplace_check
        CHECK (
            marketplace IN (
                'ebay',
                'buyee',
                'gripsweat'
            )
        );
