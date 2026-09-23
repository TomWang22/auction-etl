DROP VIEW IF EXISTS warehouse.auction_collector_review;
DROP VIEW IF EXISTS warehouse.auction_collector_effective;

ALTER TABLE warehouse.auction
    DROP COLUMN IF EXISTS label;
