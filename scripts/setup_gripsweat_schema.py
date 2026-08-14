"""Create normalized Gripsweat source and completed-sale tables."""

from __future__ import annotations

from sqlalchemy import text

from auction_etl.database.session import engine


STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS warehouse.gripsweat_source (
        id BIGSERIAL PRIMARY KEY,
        source_name TEXT NOT NULL UNIQUE,
        configured_artist TEXT NOT NULL,
        search_query TEXT NOT NULL,
        url_template TEXT NOT NULL,
        sort_by TEXT NOT NULL DEFAULT 'date',
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        max_pages INTEGER NOT NULL CHECK (max_pages > 0),
        delay_seconds NUMERIC(8, 3)
            NOT NULL
            CHECK (delay_seconds >= 0),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS warehouse.gripsweat_sale (
        id BIGSERIAL PRIMARY KEY,
        source_id BIGINT NOT NULL
            REFERENCES warehouse.gripsweat_source(id)
            ON DELETE RESTRICT,
        source_name TEXT NOT NULL,
        configured_artist TEXT NOT NULL,
        source_query TEXT NOT NULL,
        page_number INTEGER NOT NULL
            CHECK (page_number > 0),
        source_position INTEGER,
        gripsweat_item_key TEXT NOT NULL,
        gripsweat_url TEXT NOT NULL,
        title TEXT,
        sold_price NUMERIC(18, 2),
        currency VARCHAR(3),
        sold_at DATE,
        sold_at_text TEXT,
        image_url TEXT,
        original_marketplace TEXT,
        original_listing_id TEXT,
        raw_text TEXT,
        first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT gripsweat_sale_source_item_unique
            UNIQUE (source_name, gripsweat_item_key),
        CONSTRAINT gripsweat_sale_url_unique
            UNIQUE (gripsweat_url)
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS
        gripsweat_sale_original_listing_unique
    ON warehouse.gripsweat_sale (
        original_marketplace,
        original_listing_id
    )
    WHERE original_marketplace IS NOT NULL
      AND original_listing_id IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS
        gripsweat_sale_artist_date_index
    ON warehouse.gripsweat_sale (
        configured_artist,
        sold_at DESC
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS
        gripsweat_sale_title_search_index
    ON warehouse.gripsweat_sale
    USING GIN (to_tsvector('simple', COALESCE(title, '')))
    """,
)


def main() -> int:
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE SCHEMA IF NOT EXISTS warehouse"
            )
        )

        for statement in STATEMENTS:
            connection.execute(text(statement))

    print("Created or verified:")
    print("  warehouse.gripsweat_source")
    print("  warehouse.gripsweat_sale")
    print("  unique Gripsweat URL/item constraints")
    print("  partial unique original-listing constraint")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
