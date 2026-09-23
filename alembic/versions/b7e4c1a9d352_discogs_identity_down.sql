DROP VIEW IF EXISTS warehouse.auction_collector_review;
DROP VIEW IF EXISTS warehouse.auction_collector_effective;

ALTER TABLE warehouse.auction
    DROP CONSTRAINT IF EXISTS auction_identity_status_valid;

ALTER TABLE warehouse.auction
    DROP CONSTRAINT IF EXISTS auction_identity_source_valid;

DROP INDEX IF EXISTS warehouse.auction_identity_status_idx;

ALTER TABLE warehouse.auction
    DROP COLUMN IF EXISTS discogs_shortlist_fetched_at,
    DROP COLUMN IF EXISTS discogs_shortlist,
    DROP COLUMN IF EXISTS discogs_thumb_url,
    DROP COLUMN IF EXISTS identity_status_changed_at,
    DROP COLUMN IF EXISTS identity_filled_at,
    DROP COLUMN IF EXISTS identity_source,
    DROP COLUMN IF EXISTS identity_status,
    DROP COLUMN IF EXISTS image_url;

DROP INDEX IF EXISTS warehouse.pressing_identity_discogs_release_uidx;

ALTER TABLE warehouse.pressing_identity
    DROP COLUMN IF EXISTS discogs_uri,
    DROP COLUMN IF EXISTS discogs_master_id,
    DROP COLUMN IF EXISTS discogs_release_id,
    DROP COLUMN IF EXISTS label_id;

DROP TABLE IF EXISTS warehouse.label;
