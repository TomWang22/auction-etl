ALTER TABLE warehouse.auction
    ADD COLUMN IF NOT EXISTS label varchar(255);

COMMENT ON COLUMN warehouse.auction.label IS
    'Extracted record label from listing text; feeds pressing-library matching.';

UPDATE warehouse.auction AS auction
SET label = listing.label
FROM staging.listing AS listing
WHERE auction.marketplace = listing.marketplace
  AND auction.listing_id = listing.listing_id
  AND auction.label IS NULL
  AND listing.label IS NOT NULL
  AND BTRIM(listing.label) <> '';
