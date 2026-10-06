from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

import psycopg
from sqlalchemy import text
from sqlalchemy.engine import Engine

MARKETPLACES = frozenset({"buyee", "ebay", "gripsweat"})


@dataclass(frozen=True, slots=True)
class VisibilityPublication:
    """Account-visible population for one marketplace after publication."""

    marketplace: str
    visible_count: int
    visible_added: int


def _psycopg_url(database_url: str) -> str:
    normalized = database_url.strip()
    for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://"):
        if normalized.startswith(prefix):
            return "postgresql://" + normalized[len(prefix):]
    return normalized


def _uuid(value: str | uuid.UUID, name: str) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid {name}: {value!r}") from exc


def publish_marketplace_visibility(
    database_url: str,
    *,
    account_id: str | uuid.UUID,
    refresh_job_id: str | uuid.UUID,
    marketplace: str,
) -> VisibilityPublication:
    """Publish one synchronized marketplace to the account Review surface."""

    normalized = marketplace.strip().casefold()
    if normalized not in MARKETPLACES:
        raise ValueError(f"Unsupported marketplace: {marketplace!r}")

    parameters = {
        "account_id": _uuid(account_id, "account_id"),
        "job_id": _uuid(refresh_job_id, "refresh_job_id"),
        "marketplace": normalized,
    }

    if normalized == "gripsweat":
        insert_sql = """
            WITH candidates AS (
                SELECT DISTINCT
                    COALESCE(
                        NULLIF(btrim(original_listing_id), ''),
                        substring(gripsweat_url FROM '/item/([0-9]{9,15})')
                    ) AS listing_id
                FROM warehouse.gripsweat_sale
            ),
            eligible AS (
                SELECT listing_id
                FROM candidates
                WHERE listing_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM warehouse.auction AS auction
                      WHERE lower(btrim(auction.marketplace)) = 'ebay'
                        AND auction.listing_id = candidates.listing_id
                  )
            )
            INSERT INTO account.auction_listing (
                account_id,
                marketplace,
                listing_id,
                source_kind,
                source_refresh_job_id
            )
            SELECT
                %(account_id)s,
                'gripsweat',
                listing_id,
                'marketplace-refresh',
                %(job_id)s
            FROM eligible
            ON CONFLICT (account_id, marketplace, listing_id)
            DO NOTHING
        """
    else:
        insert_sql = """
            WITH candidates AS (
                SELECT DISTINCT
                    lower(btrim(marketplace)) AS marketplace,
                    btrim(listing_id) AS listing_id
                FROM warehouse.auction
                WHERE lower(btrim(marketplace)) = %(marketplace)s
                  AND btrim(listing_id) <> ''
            )
            INSERT INTO account.auction_listing (
                account_id,
                marketplace,
                listing_id,
                source_kind,
                source_refresh_job_id
            )
            SELECT
                %(account_id)s,
                marketplace,
                listing_id,
                'marketplace-refresh',
                %(job_id)s
            FROM candidates
            ON CONFLICT (account_id, marketplace, listing_id)
            DO NOTHING
        """

    with psycopg.connect(_psycopg_url(database_url)) as connection:
        connection.execute("SET LOCAL statement_timeout = '30s'")
        connection.execute(insert_sql, parameters)
        visible_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM account.auction_listing
                WHERE account_id = %(account_id)s
                  AND marketplace = %(marketplace)s
                """,
                parameters,
            ).fetchone()[0]
        )
        visible_added = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM account.auction_listing
                WHERE account_id = %(account_id)s
                  AND marketplace = %(marketplace)s
                  AND source_refresh_job_id = %(job_id)s
                """,
                parameters,
            ).fetchone()[0]
        )

    return VisibilityPublication(
        marketplace=normalized,
        visible_count=visible_count,
        visible_added=visible_added,
    )


_ATTACHED_WAREHOUSE_GENERATION: dict[str, int] = {}


NATIVE_VISIBILITY_SQL = """
    WITH candidates AS (
        SELECT DISTINCT
            lower(btrim(marketplace)) AS marketplace,
            btrim(listing_id) AS listing_id
        FROM warehouse.auction
        WHERE lower(btrim(marketplace)) = :marketplace
          AND btrim(listing_id) <> ''
    )
    INSERT INTO account.auction_listing (
        account_id,
        marketplace,
        listing_id,
        source_kind
    )
    SELECT
        CAST(:account_id AS uuid),
        marketplace,
        listing_id,
        :source_kind
    FROM candidates
    ON CONFLICT (account_id, marketplace, listing_id)
    DO NOTHING
"""

GRIPSWEAT_VISIBILITY_SQL = """
    WITH candidates AS (
        SELECT DISTINCT
            COALESCE(
                NULLIF(btrim(original_listing_id), ''),
                substring(gripsweat_url FROM '/item/([0-9]{9,15})')
            ) AS listing_id
        FROM warehouse.gripsweat_sale
    ),
    eligible AS (
        SELECT listing_id
        FROM candidates
        WHERE listing_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM warehouse.auction AS auction
              WHERE lower(btrim(auction.marketplace)) = 'ebay'
                AND auction.listing_id = candidates.listing_id
          )
    )
    INSERT INTO account.auction_listing (
        account_id,
        marketplace,
        listing_id,
        source_kind
    )
    SELECT
        CAST(:account_id AS uuid),
        'gripsweat',
        listing_id,
        :source_kind
    FROM eligible
    ON CONFLICT (account_id, marketplace, listing_id)
    DO NOTHING
"""


def attach_development_warehouse_visibility(
    engine: Engine,
    account_id: str | uuid.UUID,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Attach local warehouse identities to the signed-in development account.

    Yahoo OIDC only identifies the operator. Local warehouse facts stay
    invisible until they exist in account.auction_listing. Production
    first-login workspaces remain empty.
    """
    from auction_etl.auth.oidc_production import classify_oidc_runtime

    if classify_oidc_runtime(environ) != "development":
        return 0

    account_uuid = _uuid(account_id, "account_id")
    with engine.connect() as connection:
        generation = int(
            connection.execute(
                text(
                    """
                    SELECT
                      (SELECT COUNT(*) FROM warehouse.auction)
                      + (SELECT COUNT(*) FROM warehouse.gripsweat_sale)
                    """
                )
            ).scalar_one()
        )
    cache_key = str(account_uuid)
    if _ATTACHED_WAREHOUSE_GENERATION.get(cache_key) == generation:
        return 0

    added = 0
    with engine.begin() as connection:
        before = int(
            connection.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM account.auction_listing
                    WHERE account_id = CAST(:account_id AS uuid)
                    """
                ),
                {"account_id": account_uuid},
            ).scalar_one()
        )
        for marketplace in ("buyee", "ebay"):
            connection.execute(
                text(NATIVE_VISIBILITY_SQL),
                {
                    "account_id": account_uuid,
                    "marketplace": marketplace,
                    "source_kind": "local-warehouse",
                },
            )
        connection.execute(
            text(GRIPSWEAT_VISIBILITY_SQL),
            {
                "account_id": account_uuid,
                "source_kind": "local-warehouse",
            },
        )
        after = int(
            connection.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM account.auction_listing
                    WHERE account_id = CAST(:account_id AS uuid)
                    """
                ),
                {"account_id": account_uuid},
            ).scalar_one()
        )
        added = after - before
    _ATTACHED_WAREHOUSE_GENERATION[cache_key] = generation
    return added


def publish_current_refresh_visibility(
    database_url: str,
    *,
    marketplace: str,
) -> VisibilityPublication | None:
    """Publish only when the runner is owned by a durable cloud refresh."""

    account_id = os.environ.get("AUCTION_ACCOUNT_ID", "").strip()
    refresh_job_id = os.environ.get("AUCTION_REFRESH_JOB_ID", "").strip()
    if not account_id and not refresh_job_id:
        return None
    if not account_id or not refresh_job_id:
        raise RuntimeError(
            "AUCTION_ACCOUNT_ID and AUCTION_REFRESH_JOB_ID must be set together."
        )

    return publish_marketplace_visibility(
        database_url,
        account_id=account_id,
        refresh_job_id=refresh_job_id,
        marketplace=marketplace,
    )
