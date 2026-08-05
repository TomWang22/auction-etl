"""Read-only access to immutable listing completeness history."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Engine, create_engine, text


def engine_from_environment() -> Engine:
    """Create the configured PostgreSQL engine."""
    database_url = os.environ.get(
        "DATABASE_URL",
        ""
    ).strip()

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is required."
        )

    return create_engine(
        database_url,
        pool_pre_ping=True,
    )


def _dictionary(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a plain dictionary."""
    return {
        str(key):
            item
        for key, item in value.items()
    }


def list_assigned_listings(
    engine: Engine,
) -> list[dict[str, Any]]:
    """Return every exact-pressing assignment."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                WITH assignment_identity AS (
                    SELECT
                        assignment.marketplace,
                        assignment.listing_id,
                        assignment.pressing_id,
                        pressing.catalog_number,
                        pressing.media_type,
                        to_jsonb(
                            pressing
                        ) AS pressing_payload,
                        to_jsonb(
                            family
                        ) AS family_payload
                    FROM warehouse.auction_pressing_assignment
                        AS assignment
                    JOIN warehouse.pressing_identity AS pressing
                      ON pressing.id =
                            assignment.pressing_id
                    LEFT JOIN warehouse.release_family AS family
                      ON (
                          to_jsonb(
                              family
                          ) ->> 'id'
                      ) = (
                          to_jsonb(
                              pressing
                          ) ->> 'release_family_id'
                      )
                )
                SELECT
                    marketplace,
                    listing_id,
                    pressing_id,
                    catalog_number,
                    COALESCE(
                        NULLIF(
                            pressing_payload
                                ->> 'display_artist',
                            ''
                        ),
                        NULLIF(
                            family_payload
                                ->> 'display_artist',
                            ''
                        ),
                        NULLIF(
                            pressing_payload
                                ->> 'canonical_artist',
                            ''
                        ),
                        NULLIF(
                            family_payload
                                ->> 'canonical_artist',
                            ''
                        ),
                        NULLIF(
                            pressing_payload
                                ->> 'artist',
                            ''
                        ),
                        NULLIF(
                            family_payload
                                ->> 'artist',
                            ''
                        ),
                        NULLIF(
                            family_payload
                                ->> 'artist_name',
                            ''
                        ),
                        'Unknown artist'
                    ) AS display_artist,
                    COALESCE(
                        NULLIF(
                            pressing_payload
                                ->> 'display_title',
                            ''
                        ),
                        NULLIF(
                            family_payload
                                ->> 'display_title',
                            ''
                        ),
                        NULLIF(
                            pressing_payload
                                ->> 'canonical_title',
                            ''
                        ),
                        NULLIF(
                            family_payload
                                ->> 'canonical_title',
                            ''
                        ),
                        NULLIF(
                            pressing_payload
                                ->> 'title',
                            ''
                        ),
                        NULLIF(
                            family_payload
                                ->> 'title',
                            ''
                        ),
                        NULLIF(
                            family_payload
                                ->> 'release_title',
                            ''
                        ),
                        'Unknown title'
                    ) AS display_title,
                    media_type
                FROM assignment_identity
                ORDER BY
                    display_artist,
                    display_title,
                    catalog_number,
                    marketplace,
                    listing_id
                """
            )
        ).mappings().all()

    return [
        _dictionary(
            row
        )
        for row in rows
    ]


def snapshot_coverage(
    engine: Engine,
) -> dict[str, int]:
    """Return current assignment and snapshot coverage."""
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (
                        marketplace,
                        listing_id
                    )
                        marketplace,
                        listing_id
                    FROM system.listing_completeness_snapshot
                    ORDER BY
                        marketplace,
                        listing_id,
                        created_at DESC,
                        id DESC
                )
                SELECT
                    (
                        SELECT COUNT(*)
                        FROM warehouse.auction_pressing_assignment
                    )::integer AS assigned_listings,
                    (
                        SELECT COUNT(*)
                        FROM latest
                    )::integer AS listings_with_snapshots,
                    (
                        SELECT COUNT(*)
                        FROM system.listing_completeness_snapshot
                    )::integer AS snapshot_rows
                """
            )
        ).mappings().one()

    return {
        key:
            int(
                value
            )
        for key, value in row.items()
    }


def current_snapshot(
    engine: Engine,
    marketplace: str,
    listing_id: str,
) -> dict[str, Any] | None:
    """Return the latest immutable completeness snapshot."""
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT *
                FROM system.listing_completeness_snapshot
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                ORDER BY
                    created_at DESC,
                    id DESC
                LIMIT 1
                """
            ),
            {
                "marketplace":
                    marketplace,
                "listing_id":
                    listing_id,
            },
        ).mappings().first()

    if row is None:
        return None

    return _dictionary(
        row
    )


def list_snapshots(
    engine: Engine,
    marketplace: str,
    listing_id: str,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return immutable snapshots newest first."""
    safe_limit = max(
        1,
        min(
            int(
                limit
            ),
            1_000,
        ),
    )

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT *
                FROM system.listing_completeness_snapshot
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                ORDER BY
                    created_at DESC,
                    id DESC
                LIMIT :limit
                """
            ),
            {
                "marketplace":
                    marketplace,
                "listing_id":
                    listing_id,
                "limit":
                    safe_limit,
            },
        ).mappings().all()

    return [
        _dictionary(
            row
        )
        for row in rows
    ]


def list_timeline(
    engine: Engine,
    marketplace: str,
    listing_id: str,
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return chronological source and completeness differences."""
    safe_limit = max(
        1,
        min(
            int(
                limit
            ),
            2_000,
        ),
    )

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT *
                FROM system.listing_completeness_timeline
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                ORDER BY
                    occurred_at DESC,
                    event_id DESC
                LIMIT :limit
                """
            ),
            {
                "marketplace":
                    marketplace,
                "listing_id":
                    listing_id,
                "limit":
                    safe_limit,
            },
        ).mappings().all()

    return [
        _dictionary(
            row
        )
        for row in rows
    ]
