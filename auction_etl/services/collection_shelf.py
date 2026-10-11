"""Match purchased copies to stored sales and write the shelf."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine

from auction_etl.services.account_scope import account_transaction
from auction_etl.services.collection_import import (
    ParsedPurchase,
    is_collected_music,
)
from auction_etl.services.discogs_identity import fold_catalog


OWNED_COPY_DDL = """
CREATE TABLE IF NOT EXISTS warehouse.owned_copy (
    id bigserial PRIMARY KEY,
    account_id uuid NOT NULL,
    source varchar NOT NULL,
    external_id varchar NOT NULL,
    title text,
    seller varchar,
    catalog_number varchar,
    pressing_id bigint,
    paid_amount numeric(18, 2),
    paid_currency varchar,
    paid_on date,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (account_id, source, external_id)
)
"""


@dataclass(frozen=True)
class PressingChoice:
    """One pressing a purchase can be attached to."""

    pressing_id: int
    catalog_number: str
    artist_name: str
    album_title: str


@dataclass(frozen=True)
class ImportMatch:
    """Where one purchased copy lands on the shelf."""

    purchase: ParsedPurchase
    status: str
    marketplace: str
    listing_id: str
    pressings: tuple[PressingChoice, ...]
    reason: str


def ensure_owned_copy_table(engine: Engine) -> None:
    """Add the shop-order shelf if this warehouse does not have it yet."""

    with engine.begin() as connection:
        connection.execute(text(OWNED_COPY_DDL))
        connection.execute(
            text(
                """
                ALTER TABLE warehouse.owned_copy
                    ADD COLUMN IF NOT EXISTS billing_note text
                """
            )
        )


def classify_purchases(
    engine: Engine,
    account_id: str,
    purchases: tuple[ParsedPurchase, ...] | list[ParsedPurchase],
) -> list[ImportMatch]:
    """Match each purchase to a stored listing, a pressing, or a gap."""

    rows = list(purchases)
    if not rows:
        return []

    listing_keys = {
        (row.source, row.external_id)
        for row in rows
        if row.source in {"ebay", "buyee"}
    }
    listings = _listings_for(engine, account_id, listing_keys)
    owned = _owned_keys(engine, account_id)
    purchased = _purchased_keys(engine, account_id)
    owned_catalogs = _owned_catalog_folds(engine, account_id)
    folds: set[str] = set()
    for row in rows:
        folds.update(_catalog_search_folds(row.catalog_number))
    pressings = _pressings_for(engine, folds)
    matches: list[ImportMatch] = []
    for purchase in rows:
        matches.append(
            _classify_one(
                purchase,
                listings=listings,
                owned=owned,
                purchased=purchased,
                owned_catalogs=owned_catalogs,
                pressings=pressings,
            )
        )
    return matches


def mark_listing_purchased(
    engine: Engine,
    *,
    account_id: str,
    user_id: str,
    marketplace: str,
    listing_id: str,
    paid_amount: Decimal | None,
    paid_currency: str,
    paid_on: date | None,
    billing_note: str = "",
) -> None:
    """Mark one stored sale as a copy this account bought."""

    with account_transaction(
        engine,
        account_id=UUID(str(account_id)),
        user_id=UUID(str(user_id)),
    ) as connection:
        visible = connection.execute(
            text(
                """
                SELECT 1
                FROM account.auction_listing
                WHERE account_id = CAST(:account_id AS uuid)
                  AND lower(btrim(marketplace)) = lower(btrim(:marketplace))
                  AND listing_id = :listing_id
                """
            ),
            {
                "account_id": account_id,
                "marketplace": marketplace,
                "listing_id": listing_id,
            },
        ).scalar_one_or_none()
        if visible is None:
            raise PermissionError(
                "That listing is not in this account yet."
            )
        connection.execute(
            text(
                """
                INSERT INTO warehouse.auction_collector (
                    account_id,
                    marketplace,
                    listing_id
                )
                VALUES (
                    CAST(:account_id AS uuid),
                    CAST(:marketplace AS character varying),
                    CAST(:listing_id AS character varying)
                )
                ON CONFLICT (
                    account_id,
                    marketplace,
                    listing_id
                )
                WHERE account_id IS NOT NULL
                DO NOTHING
                """
            ),
            {
                "account_id": account_id,
                "marketplace": marketplace,
                "listing_id": listing_id,
            },
        )
        connection.execute(
            text(
                """
                UPDATE warehouse.auction_collector
                SET manual_purchased = TRUE,
                    manual_purchase_price = :paid_amount,
                    manual_purchase_currency = :paid_currency,
                    manual_purchase_date = :paid_on,
                    manual_purchase_notes = CASE
                        WHEN :billing_note <> '' THEN :billing_note
                        ELSE manual_purchase_notes
                    END,
                    purchase_updated_at = now(),
                    updated_at = now()
                WHERE account_id = CAST(:account_id AS uuid)
                  AND marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "account_id": account_id,
                "marketplace": marketplace,
                "listing_id": listing_id,
                "paid_amount": paid_amount,
                "paid_currency": paid_currency or None,
                "paid_on": paid_on,
                "billing_note": billing_note or "",
            },
        )


def save_billing_note(
    engine: Engine,
    *,
    account_id: str,
    purchase: ParsedPurchase,
    marketplace: str = "",
    listing_id: str = "",
    user_id: str = "",
) -> int:
    """Store the charge breakdown on a copy already on the shelf.

    The item price is left as it is. ``marketplace`` and ``listing_id``
    name the shelf row when the bill itself has a different id.
    Returns how many rows were written.
    """

    note = purchase.billing_note.strip()
    if not note:
        return 0
    marketplace = str(marketplace or "").strip()
    listing_id = str(listing_id or "").strip()
    if listing_id.lower() in {"nan", "none"}:
        listing_id = ""
    folded = fold_catalog(purchase.catalog_number)
    updated = 0

    def _run(connection) -> None:
        nonlocal updated

        if marketplace and listing_id:
            result = connection.execute(
                text(
                    """
                    UPDATE warehouse.auction_collector
                    SET manual_purchase_notes = :billing_note,
                        purchase_updated_at = now()
                    WHERE account_id = CAST(:account_id AS uuid)
                      AND lower(btrim(marketplace::text)) =
                          lower(btrim(:marketplace))
                      AND listing_id::text = CAST(:listing_id AS text)
                      AND manual_purchased IS TRUE
                    """
                ),
                {
                    "account_id": account_id,
                    "marketplace": marketplace,
                    "listing_id": listing_id,
                    "billing_note": note,
                },
            )
            updated += max(result.rowcount or 0, 0)
            result = connection.execute(
                text(
                    """
                    UPDATE warehouse.owned_copy
                    SET billing_note = :billing_note,
                        updated_at = now()
                    WHERE account_id = CAST(:account_id AS uuid)
                      AND lower(btrim(source)) = lower(btrim(:marketplace))
                      AND external_id::text = CAST(:listing_id AS text)
                    """
                ),
                {
                    "account_id": account_id,
                    "marketplace": marketplace,
                    "listing_id": listing_id,
                    "billing_note": note,
                },
            )
            updated += max(result.rowcount or 0, 0)
        if (
            updated == 0
            and purchase.source in {"ebay", "buyee"}
            and purchase.external_id
        ):
            result = connection.execute(
                text(
                    """
                    UPDATE warehouse.auction_collector
                    SET manual_purchase_notes = :billing_note,
                        purchase_updated_at = now()
                    WHERE account_id = CAST(:account_id AS uuid)
                      AND lower(btrim(marketplace::text)) =
                          lower(btrim(:marketplace))
                      AND listing_id::text = CAST(:listing_id AS text)
                      AND manual_purchased IS TRUE
                    """
                ),
                {
                    "account_id": account_id,
                    "marketplace": purchase.source,
                    "listing_id": str(purchase.external_id).strip(),
                    "billing_note": note,
                },
            )
            updated += max(result.rowcount or 0, 0)
        if updated == 0 and folded:
            result = connection.execute(
                text(
                    """
                    UPDATE warehouse.auction_collector owned
                    SET manual_purchase_notes = :billing_note,
                        purchase_updated_at = now()
                    FROM warehouse.auction_collector_effective sale
                    WHERE owned.account_id = CAST(:account_id AS uuid)
                      AND owned.manual_purchased IS TRUE
                      AND sale.marketplace::text = owned.marketplace::text
                      AND sale.listing_id::text = owned.listing_id::text
                      AND regexp_replace(
                            upper(coalesce(sale.effective_catalog_number, '')),
                            '[^A-Z0-9]',
                            '',
                            'g'
                          ) = :folded
                    """
                ),
                {
                    "account_id": account_id,
                    "billing_note": note,
                    "folded": folded,
                },
            )
            updated += max(result.rowcount or 0, 0)
            result = connection.execute(
                text(
                    """
                    UPDATE warehouse.owned_copy
                    SET billing_note = :billing_note,
                        updated_at = now()
                    WHERE account_id = CAST(:account_id AS uuid)
                      AND regexp_replace(
                            upper(coalesce(catalog_number, '')),
                            '[^A-Z0-9]',
                            '',
                            'g'
                          ) = :folded
                    """
                ),
                {
                    "account_id": account_id,
                    "billing_note": note,
                    "folded": folded,
                },
            )
            updated += max(result.rowcount or 0, 0)

    if user_id:
        with account_transaction(
            engine,
            account_id=UUID(str(account_id)),
            user_id=UUID(str(user_id)),
        ) as connection:
            _run(connection)
    else:
        with engine.begin() as connection:
            _run(connection)
    return updated


def save_owned_copy(
    engine: Engine,
    *,
    account_id: str,
    purchase: ParsedPurchase,
    catalog_number: str,
    pressing_id: int | None,
    paid_amount: Decimal | None,
    paid_currency: str,
    paid_on: date | None,
) -> None:
    """Store a shop order that was never scraped as a marketplace sale."""

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO warehouse.owned_copy (
                    account_id,
                    source,
                    external_id,
                    title,
                    seller,
                    catalog_number,
                    pressing_id,
                    paid_amount,
                    paid_currency,
                    paid_on,
                    billing_note
                )
                VALUES (
                    CAST(:account_id AS uuid),
                    :source,
                    :external_id,
                    :title,
                    :seller,
                    :catalog_number,
                    :pressing_id,
                    :paid_amount,
                    :paid_currency,
                    :paid_on,
                    :billing_note
                )
                ON CONFLICT (account_id, source, external_id)
                DO UPDATE SET
                    title = EXCLUDED.title,
                    seller = EXCLUDED.seller,
                    catalog_number = EXCLUDED.catalog_number,
                    pressing_id = EXCLUDED.pressing_id,
                    paid_amount = EXCLUDED.paid_amount,
                    paid_currency = EXCLUDED.paid_currency,
                    paid_on = EXCLUDED.paid_on,
                    billing_note = EXCLUDED.billing_note,
                    updated_at = now()
                """
            ),
            {
                "account_id": account_id,
                "source": purchase.source,
                "external_id": purchase.external_id,
                "title": purchase.title,
                "seller": purchase.seller,
                "catalog_number": catalog_number or purchase.catalog_number,
                "pressing_id": pressing_id,
                "paid_amount": paid_amount,
                "paid_currency": paid_currency or None,
                "paid_on": paid_on,
                "billing_note": purchase.billing_note or "",
            },
        )


def search_visible_sales(
    engine: Engine,
    account_id: str,
    query: str,
) -> list[dict[str, Any]]:
    """Find stored sales this account can mark as purchased."""

    term = query.strip()
    if len(term) < 2:
        return []
    with engine.connect() as connection:
        result = connection.execute(
            text(
                """
                SELECT
                    sale.marketplace::text AS marketplace,
                    sale.listing_id::text AS listing_id,
                    sale.seller,
                    sale.title,
                    sale.effective_catalog_number AS catalog_number,
                    sale.effective_artist AS artist_name,
                    sale.gross_price,
                    sale.currency,
                    COALESCE(sale.ended_at, sale.closing_at)::date AS sold_on
                FROM warehouse.auction_collector_effective sale
                WHERE EXISTS (
                    SELECT 1
                    FROM account.auction_listing owned
                    WHERE owned.account_id = CAST(:account_id AS uuid)
                      AND lower(btrim(owned.marketplace)) =
                          lower(btrim(sale.marketplace::text))
                      AND owned.listing_id = sale.listing_id
                )
                  AND (
                    sale.effective_catalog_number ILIKE :query
                    OR sale.title ILIKE :query
                    OR sale.seller ILIKE :query
                    OR COALESCE(sale.effective_artist, sale.artist) ILIKE :query
                  )
                ORDER BY COALESCE(sale.ended_at, sale.closing_at) DESC NULLS LAST
                LIMIT 12
                """
            ),
            {"account_id": account_id, "query": f"%{term}%"},
        )
        return [dict(row) for row in result.mappings()]


def _classify_one(
    purchase: ParsedPurchase,
    *,
    listings: dict[tuple[str, str], dict[str, Any]],
    owned: set[tuple[str, str]],
    purchased: set[tuple[str, str]],
    owned_catalogs: set[str],
    pressings: dict[str, tuple[PressingChoice, ...]],
) -> ImportMatch:
    if not is_collected_music(purchase.title):
        return ImportMatch(
            purchase=purchase,
            status="left_out",
            marketplace="",
            listing_id="",
            pressings=(),
            reason="Not music",
        )

    key = (purchase.source, purchase.external_id)
    folded_catalog = fold_catalog(purchase.catalog_number)
    if key in owned or key in purchased or (
        folded_catalog and folded_catalog in owned_catalogs
    ):
        return ImportMatch(
            purchase=purchase,
            status="already",
            marketplace=purchase.source if purchase.source in {"ebay", "buyee"} else "",
            listing_id=purchase.external_id if purchase.source in {"ebay", "buyee"} else "",
            pressings=(),
            reason="Already on your shelf",
        )

    listing = listings.get(key)
    if listing is not None and listing["visible"]:
        return ImportMatch(
            purchase=purchase,
            status="ready",
            marketplace=str(listing["marketplace"]),
            listing_id=str(listing["listing_id"]),
            pressings=(),
            reason="",
        )

    if (
        purchase.external_id.startswith("log:")
        and not fold_catalog(purchase.catalog_number)
        and purchase.title.strip()
    ):
        return ImportMatch(
            purchase=purchase,
            status="new_copy",
            marketplace="",
            listing_id="",
            pressings=(),
            reason="",
        )

    choices = pressings.get(fold_catalog(purchase.catalog_number), ())
    if len(choices) == 1 or (purchase.catalog_number and len(choices) == 0):
        return ImportMatch(
            purchase=purchase,
            status="new_copy",
            marketplace="",
            listing_id="",
            pressings=choices,
            reason="",
        )
    if len(choices) > 1:
        return ImportMatch(
            purchase=purchase,
            status="pick",
            marketplace="",
            listing_id="",
            pressings=choices,
            reason="More than one pressing uses this catalog",
        )
    return ImportMatch(
        purchase=purchase,
        status="pick",
        marketplace="",
        listing_id="",
        pressings=(),
        reason="Type the catalog number",
    )


def _listings_for(
    engine: Engine,
    account_id: str,
    keys: set[tuple[str, str]],
) -> dict[tuple[str, str], dict[str, Any]]:
    found: dict[tuple[str, str], dict[str, Any]] = {}
    grouped: dict[str, list[str]] = {}
    for source, external_id in keys:
        grouped.setdefault(source, []).append(external_id)
    with engine.connect() as connection:
        for source, listing_ids in grouped.items():
            result = connection.execute(
                text(
                    """
                    SELECT
                        lower(auction.marketplace::text) AS marketplace,
                        auction.listing_id::text AS listing_id,
                        EXISTS (
                            SELECT 1
                            FROM account.auction_listing owned
                            WHERE owned.account_id = CAST(:account_id AS uuid)
                              AND lower(btrim(owned.marketplace)) =
                                  lower(btrim(auction.marketplace::text))
                              AND owned.listing_id = auction.listing_id
                        ) AS visible
                    FROM warehouse.auction auction
                    WHERE lower(auction.marketplace::text) = :marketplace
                      AND auction.listing_id = ANY(:listing_ids)
                    """
                ),
                {
                    "account_id": account_id,
                    "marketplace": source,
                    "listing_ids": listing_ids,
                },
            )
            for row in result.mappings():
                found[(str(row["marketplace"]), str(row["listing_id"]))] = dict(row)
    return found


def _owned_keys(engine: Engine, account_id: str) -> set[tuple[str, str]]:
    with engine.connect() as connection:
        result = connection.execute(
            text(
                """
                SELECT source, external_id
                FROM warehouse.owned_copy
                WHERE account_id = CAST(:account_id AS uuid)
                """
            ),
            {"account_id": account_id},
        )
        return {(str(row.source), str(row.external_id)) for row in result}


def _owned_catalog_folds(engine: Engine, account_id: str) -> set[str]:
    with engine.connect() as connection:
        collected = connection.execute(
            text(
                """
                SELECT sale.effective_catalog_number AS catalog_number
                FROM warehouse.auction_collector owned
                JOIN warehouse.auction_collector_effective sale
                  ON sale.marketplace::text = owned.marketplace::text
                 AND sale.listing_id::text = owned.listing_id::text
                WHERE owned.account_id = CAST(:account_id AS uuid)
                  AND owned.manual_purchased IS TRUE
                """
            ),
            {"account_id": account_id},
        )
        copied = connection.execute(
            text(
                """
                SELECT catalog_number
                FROM warehouse.owned_copy
                WHERE account_id = CAST(:account_id AS uuid)
                """
            ),
            {"account_id": account_id},
        )
    folds = {fold_catalog(row.catalog_number) for row in collected}
    folds.update(fold_catalog(row.catalog_number) for row in copied)
    folds.discard("")
    return folds


def _purchased_keys(engine: Engine, account_id: str) -> set[tuple[str, str]]:
    with engine.connect() as connection:
        result = connection.execute(
            text(
                """
                SELECT lower(marketplace::text) AS marketplace,
                       listing_id::text AS listing_id
                FROM warehouse.auction_collector
                WHERE account_id = CAST(:account_id AS uuid)
                  AND manual_purchased IS TRUE
                """
            ),
            {"account_id": account_id},
        )
        return {(str(row.marketplace), str(row.listing_id)) for row in result}


def _catalog_search_folds(value: str | None) -> set[str]:
    folded = fold_catalog(value)
    compact = "".join(character for character in str(value or "").upper() if character.isalnum())
    return {item for item in (folded, compact) if item}


def _pressings_for(
    engine: Engine,
    folds: set[str],
) -> dict[str, tuple[PressingChoice, ...]]:
    wanted = {fold for fold in folds if fold}
    if not wanted:
        return {}
    with engine.connect() as connection:
        result = connection.execute(
            text(
                """
                SELECT
                    pressing.id AS pressing_id,
                    pressing.catalog_number,
                    COALESCE(family.display_artist, '') AS artist_name,
                    COALESCE(family.display_title, '') AS album_title
                FROM warehouse.pressing_identity pressing
                LEFT JOIN warehouse.release_family family
                  ON family.id = pressing.release_family_id
                WHERE regexp_replace(
                    upper(coalesce(pressing.catalog_number, '')),
                    '[^A-Z0-9]',
                    '',
                    'g'
                ) = ANY(:folds)
                   OR EXISTS (
                    SELECT 1
                    FROM unnest(CAST(:folds AS text[])) AS wanted(fold)
                    WHERE length(wanted.fold) >= 6
                      AND regexp_replace(
                        upper(coalesce(pressing.catalog_number, '')),
                        '[^A-Z0-9]',
                        '',
                        'g'
                      ) LIKE wanted.fold || '%'
                   )
                """
            ),
            {"folds": list(wanted)},
        )
        grouped: dict[str, list[PressingChoice]] = {}
        for row in result.mappings():
            catalog = str(row["catalog_number"] or "")
            folded = fold_catalog(catalog)
            if folded not in wanted:
                continue
            grouped.setdefault(folded, []).append(
                PressingChoice(
                    pressing_id=int(row["pressing_id"]),
                    catalog_number=catalog,
                    artist_name=str(row["artist_name"] or ""),
                    album_title=str(row["album_title"] or ""),
                )
            )
    return {key: tuple(value) for key, value in grouped.items()}
