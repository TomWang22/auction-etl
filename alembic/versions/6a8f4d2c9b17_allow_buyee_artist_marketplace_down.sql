DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM account.artist_marketplace
        WHERE marketplace = 'buyee'
    ) THEN
        RAISE EXCEPTION USING
            MESSAGE = (
                'Cannot downgrade artist_marketplace_check while '
                'Buyee artist marketplace rows exist.'
            );
    END IF;
END
$$;

ALTER TABLE account.artist_marketplace
    DROP CONSTRAINT artist_marketplace_check,
    ADD CONSTRAINT artist_marketplace_check
        CHECK (
            marketplace IN (
                'ebay',
                'gripsweat'
            )
        );
