CREATE TABLE warehouse.label (
    id bigserial PRIMARY KEY,
    display_name text NOT NULL,
    discogs_label_id bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT label_display_name_not_blank
        CHECK (btrim(display_name) <> ''),
    CONSTRAINT label_discogs_id_unique
        UNIQUE (discogs_label_id)
);

COMMENT ON TABLE warehouse.label IS
    'Canonical record label chosen from Discogs, not listing extract.';

ALTER TABLE warehouse.pressing_identity
    ADD COLUMN IF NOT EXISTS label_id bigint
        REFERENCES warehouse.label(id)
        ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS discogs_release_id bigint,
    ADD COLUMN IF NOT EXISTS discogs_master_id bigint,
    ADD COLUMN IF NOT EXISTS discogs_uri text;

CREATE UNIQUE INDEX IF NOT EXISTS pressing_identity_discogs_release_uidx
    ON warehouse.pressing_identity (discogs_release_id)
    WHERE discogs_release_id IS NOT NULL;

ALTER TABLE warehouse.auction
    ADD COLUMN IF NOT EXISTS image_url text,
    ADD COLUMN IF NOT EXISTS identity_status text NOT NULL DEFAULT 'unmatched',
    ADD COLUMN IF NOT EXISTS identity_source text,
    ADD COLUMN IF NOT EXISTS identity_filled_at timestamptz,
    ADD COLUMN IF NOT EXISTS identity_status_changed_at timestamptz,
    ADD COLUMN IF NOT EXISTS discogs_thumb_url text,
    ADD COLUMN IF NOT EXISTS discogs_shortlist jsonb,
    ADD COLUMN IF NOT EXISTS discogs_shortlist_fetched_at timestamptz;

ALTER TABLE warehouse.auction
    DROP CONSTRAINT IF EXISTS auction_identity_status_valid;

ALTER TABLE warehouse.auction
    ADD CONSTRAINT auction_identity_status_valid
        CHECK (
            identity_status IN (
                'unmatched',
                'needs_review',
                'filled_auto',
                'filled_manual'
            )
        );

ALTER TABLE warehouse.auction
    DROP CONSTRAINT IF EXISTS auction_identity_source_valid;

ALTER TABLE warehouse.auction
    ADD CONSTRAINT auction_identity_source_valid
        CHECK (
            identity_source IS NULL
            OR identity_source IN ('listing', 'discogs')
        );

CREATE INDEX IF NOT EXISTS auction_identity_status_idx
    ON warehouse.auction (identity_status);

COMMENT ON COLUMN warehouse.auction.label IS
    'Listing-extract label hint for Discogs search; not the canonical choice.';

COMMENT ON COLUMN warehouse.auction.identity_status IS
    'Discogs identity fill state: unmatched, needs_review, filled_auto, filled_manual.';

UPDATE warehouse.auction AS auction
SET image_url = listing.image_url
FROM staging.listing AS listing
WHERE auction.marketplace = listing.marketplace
  AND auction.listing_id = listing.listing_id
  AND (
      auction.image_url IS NULL
      OR BTRIM(auction.image_url) = ''
  )
  AND listing.image_url IS NOT NULL
  AND BTRIM(listing.image_url) <> '';
