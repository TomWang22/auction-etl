"""Match purchased copies to stored sales and write the shelf."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine

from auction_etl.services.account_scope import account_transaction
from auction_etl.services.collection_billing import (
    BillLine,
    collection_bulk_lot,
    ensure_collection_bill_tables,
    match_record_city_bill_to_shelf,
    package_bill_from_copies,
    write_collection_bill,
)
from auction_etl.services.collection_acquisition import (
    default_delivered_on,
    default_sale_type,
    sale_type_code,
)
from auction_etl.services.collection_import import (
    ParsedPurchase,
    copy_cost_currency,
    copy_costs,
    is_collected_music,
    purchase_media,
    listing_title_is_chrome,
    listing_title_is_ocr_junk,
    listing_catalog_is_structured,
    line_price_replaces_shelf,
    ocr_promo_item_price,
)
from auction_etl.services.discogs_client import (
    DiscogsRateLimitError,
    DiscogsUnavailableError,
)
from auction_etl.services.discogs_fill import apply_release_choice, assign_known_pressing
from auction_etl.services.discogs_identity import (
    catalog_has_range,
    catno_locks_listing,
    fold_catalog,
    search_user_catalog,
    shortlist_field,
)

_EBAY_MARKETS = ("ebay", "gripsweat")
_LISTING_MARKETS = frozenset({"ebay", "buyee", "gripsweat"})
_BUYEE_ITEM_ID = re.compile(r"[a-z]\d{6,}", re.IGNORECASE)


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
    media_type: str = ""


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
        connection.execute(
            text(
                """
                ALTER TABLE warehouse.owned_copy
                    ADD COLUMN IF NOT EXISTS delivered_on date
                """
            )
        )
        connection.execute(
            text(
                """
                ALTER TABLE warehouse.owned_copy
                    ADD COLUMN IF NOT EXISTS sale_type varchar
                """
            )
        )
        connection.execute(
            text(
                """
                ALTER TABLE warehouse.owned_copy
                    ADD COLUMN IF NOT EXISTS media_type varchar
                """
            )
        )
        connection.execute(
            text(
                """
                ALTER TABLE warehouse.auction_collector
                    ADD COLUMN IF NOT EXISTS manual_delivered_on date
                """
            )
        )
        connection.execute(
            text(
                """
                ALTER TABLE warehouse.auction_collector
                    ADD COLUMN IF NOT EXISTS manual_auction_format varchar
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
    owned_rows = _owned_copy_rows(engine, account_id)
    owned_catalogs = _owned_catalog_folds(engine, account_id)
    folds: set[str] = set()
    for row in rows:
        folds.update(_catalog_search_folds(row.catalog_number))
    pressings = _pressings_for(engine, folds)
    owned_pressings = _owned_pressings_by_catalog(engine, account_id)
    matches: list[ImportMatch] = []
    for purchase in rows:
        matches.append(
            _classify_one(
                purchase,
                listings=listings,
                owned=owned,
                purchased=purchased,
                owned_rows=owned_rows,
                owned_catalogs=owned_catalogs,
                pressings=pressings,
                owned_pressings=owned_pressings,
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
    title: str = "",
    delivered_on: date | None = None,
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
                    manual_delivered_on = COALESCE(
                        manual_delivered_on,
                        CAST(:delivered_on AS date)
                    ),
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
                "delivered_on": delivered_on,
                "billing_note": billing_note or "",
            },
        )
        _repair_chrome_listing_title(
            connection,
            marketplace=marketplace,
            listing_id=listing_id,
            title=title,
        )


def _repair_chrome_listing_title(
    connection: Any,
    *,
    marketplace: str,
    listing_id: str,
    title: str,
) -> None:
    """Replace eBay order-details chrome with the purchase-history title."""

    cleaned = str(title or "").strip()
    if (
        not cleaned
        or listing_title_is_chrome(cleaned)
        or listing_title_is_ocr_junk(cleaned)
    ):
        return
    if not marketplace or not listing_id:
        return
    current = connection.execute(
        text(
            """
            SELECT title
            FROM warehouse.auction
            WHERE lower(btrim(marketplace::text)) = lower(btrim(:marketplace))
              AND listing_id::text = CAST(:listing_id AS text)
            """
        ),
        {"marketplace": marketplace, "listing_id": listing_id},
    ).scalar_one_or_none()
    if (
        current is not None
        and str(current).strip()
        and not listing_title_is_chrome(str(current))
    ):
        return
    connection.execute(
        text(
            """
            UPDATE warehouse.auction
            SET title = :title
            WHERE lower(btrim(marketplace::text)) = lower(btrim(:marketplace))
              AND listing_id::text = CAST(:listing_id AS text)
            """
        ),
        {
            "marketplace": marketplace,
            "listing_id": listing_id,
            "title": cleaned,
        },
    )


_REGION_FROM_COUNTRY = (
    ("hong kong", "Hong Kong"),
    ("taiwan", "Taiwan"),
    ("singapore", "Singapore"),
    ("malaysia", "Malaysia"),
    ("south korea", "South Korea"),
    ("korea", "South Korea"),
    ("japan", "Japan"),
    ("china", "China"),
    ("united states", "United States"),
    ("united kingdom", "United Kingdom"),
)


def collector_region_from_country(country: object) -> str | None:
    """Map a Discogs country onto the collector region menu."""

    text = str(country or "").strip()
    if not text:
        return None
    folded = text.casefold()
    if folded in {"us", "usa"}:
        return "United States"
    if folded in {"uk"}:
        return "United Kingdom"
    for needle, region in _REGION_FROM_COUNTRY:
        if needle in folded:
            return region
    return None


def collector_pressing_type_from_choice(choice: dict[str, Any]) -> str | None:
    """Promo / reissue from Discogs; a dated original is a first pressing."""

    generation = str(choice.get("generation") or "").strip().upper()
    if generation == "PROMO":
        return "PROMO_SAMPLE"
    if generation == "REISSUE":
        return "REISSUE"
    year = choice.get("release_year")
    try:
        if year is not None and int(year) > 0:
            return "FIRST_PRESSING"
    except (TypeError, ValueError):
        return None
    return None


def anatomy_values_from_choice(
    choice: dict[str, Any],
    *,
    printed_catalog: object = None,
) -> dict[str, Any]:
    """Catalog, region, discs, and pressing type Review would show from Use this."""

    catalog = str(choice.get("catalog_number") or "").strip() or None
    printed = str(printed_catalog or "").strip() or None
    if printed:
        wanted = fold_catalog(printed)
        extras = [choice.get("catalog_number"), *(choice.get("label_catnos") or ())]
        if wanted and any(
            fold_catalog(item) == wanted
            for item in extras
            if item not in {None, ""}
        ):
            catalog = printed
    discs = choice.get("disc_count")
    try:
        count = int(discs) if discs is not None else 1
    except (TypeError, ValueError):
        count = 1
    if count <= 0:
        count = 1
    return {
        "manual_catalog_number": catalog,
        "manual_region": collector_region_from_country(
            choice.get("country") or choice.get("region")
        ),
        "manual_disc_count": count,
        "manual_pressing_type": collector_pressing_type_from_choice(choice),
    }


def stub_auction_url(marketplace: str, listing_id: str) -> str:
    """URL for a shop order whose listing was never scraped."""

    market = str(marketplace or "").strip().lower()
    item = str(listing_id or "").strip()
    if market == "ebay":
        return f"https://www.ebay.com/itm/{item}"
    if market == "buyee":
        return f"https://buyee.jp/item/jdirectitems/auction/{item}"
    if market == "gripsweat":
        return f"https://gripsweat.com/item/{item}"
    return f"https://localhost/{market}/{item}"


def listing_url_for_copy(
    *,
    marketplace: str,
    listing_id: str,
    stored: str = "",
) -> str:
    """Open the shop page. Buyee always has one; eBay only when stored."""

    url = str(stored or "").strip()
    if url:
        return url
    market = str(marketplace or "").strip().lower()
    item = str(listing_id or "").strip()
    if market == "buyee" and item:
        return stub_auction_url(market, item)
    return ""


def ensure_anatomy_copy(
    engine: Engine,
    *,
    account_id: str,
    user_id: str,
    marketplace: str,
    listing_id: str,
) -> bool:
    """Make a purchased collector row, including an owned shop order with no scrape."""

    marketplace = str(marketplace or "").strip()
    listing_id = str(listing_id or "").strip()
    if not marketplace or not listing_id:
        return False
    with account_transaction(
        engine,
        account_id=UUID(str(account_id)),
        user_id=UUID(str(user_id)),
    ) as connection:
        _promote_owned_copy(
            connection,
            account_id=account_id,
            marketplace=marketplace,
            listing_id=listing_id,
        )
        found = connection.execute(
            text(
                """
                SELECT 1
                FROM warehouse.auction_collector
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
            },
        ).scalar_one_or_none()
        return found is not None


def _promote_owned_copy(
    connection: Any,
    *,
    account_id: str,
    marketplace: str,
    listing_id: str,
) -> None:
    """Turn a Bring-in shop order into a purchased collector row.

    Those copies never had a scraped listing. The stub auction keeps the
    order title, and anatomy writes the same collector fields Review uses.
    Only eBay, Buyee, and Gripsweat are added to the account listing list.
    """

    already = connection.execute(
        text(
            """
            SELECT 1
            FROM warehouse.auction_collector
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
        },
    ).scalar_one_or_none()
    if already is not None:
        return
    owned = connection.execute(
        text(
            """
            SELECT title, seller, catalog_number, pressing_id,
                   paid_amount, paid_currency, paid_on, delivered_on,
                   sale_type, billing_note
            FROM warehouse.owned_copy
            WHERE account_id = CAST(:account_id AS uuid)
              AND lower(btrim(source)) = lower(btrim(:marketplace))
              AND external_id::text = CAST(:listing_id AS text)
            """
        ),
        {
            "account_id": account_id,
            "marketplace": marketplace,
            "listing_id": listing_id,
        },
    ).mappings().first()
    if owned is None:
        return
    title = str(owned["title"] or listing_id).strip() or listing_id
    connection.execute(
        text(
            """
            INSERT INTO warehouse.auction (
                marketplace, listing_id, auction_url, seller, title,
                catalog_number, identity_status, identity_source, currency
            )
            VALUES (
                :marketplace, :listing_id, :auction_url, :seller, :title,
                :catalog_number, 'unmatched', 'listing', :currency
            )
            ON CONFLICT ON CONSTRAINT uq_auction_marketplace_listing
            DO NOTHING
            """
        ),
        {
            "marketplace": marketplace,
            "listing_id": listing_id,
            "auction_url": stub_auction_url(marketplace, listing_id),
            "seller": str(owned["seller"] or "").strip() or None,
            "title": title,
            "catalog_number": str(owned["catalog_number"] or "").strip() or None,
            "currency": (
                "JPY"
                if marketplace.casefold() == "buyee"
                else "USD"
                if marketplace.casefold() == "ebay"
                else None
            ),
        },
    )
    if marketplace.casefold() in _LISTING_MARKETS:
        connection.execute(
            text(
                """
                INSERT INTO account.auction_listing (
                    account_id, marketplace, listing_id, source_kind
                )
                VALUES (
                    CAST(:account_id AS uuid), :marketplace, :listing_id, 'collection'
                )
                ON CONFLICT (account_id, marketplace, listing_id)
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
            INSERT INTO warehouse.auction_collector (
                account_id,
                marketplace,
                listing_id,
                manual_purchased,
                manual_purchase_price,
                manual_purchase_currency,
                manual_purchase_date,
                manual_delivered_on,
                manual_auction_format,
                manual_purchase_notes,
                manual_catalog_number
            )
            VALUES (
                CAST(:account_id AS uuid),
                :marketplace,
                :listing_id,
                TRUE,
                :paid_amount,
                :paid_currency,
                :paid_on,
                :delivered_on,
                NULLIF(:sale_type, ''),
                :billing_note,
                :catalog_number
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
            "paid_amount": owned["paid_amount"],
            "paid_currency": owned["paid_currency"],
            "paid_on": owned["paid_on"],
            "delivered_on": owned["delivered_on"],
            "sale_type": str(owned["sale_type"] or ""),
            "billing_note": owned["billing_note"] or "",
            "catalog_number": str(owned["catalog_number"] or "").strip() or None,
        },
    )
    connection.execute(
        text(
            """
            DELETE FROM warehouse.owned_copy
            WHERE account_id = CAST(:account_id AS uuid)
              AND lower(btrim(source)) = lower(btrim(:marketplace))
              AND external_id::text = CAST(:listing_id AS text)
            """
        ),
        {
            "account_id": account_id,
            "marketplace": marketplace,
            "listing_id": listing_id,
        },
    )


def propagate_catalog_identity_to_siblings(
    engine: Engine,
    *,
    account_id: str,
    user_id: str,
    marketplace: str,
    listing_id: str,
    values: dict[str, Any],
    pressing_id: int | None,
    thumb_url: str | None = None,
) -> int:
    """Copy Discogs identity onto other copies of the same catalog.

    Condition and verdict stay on each copy. Catalog, region, discs, and
    pressing type are the same pressing, so they do not need another search.
    """

    marketplace = str(marketplace or "").strip()
    listing_id = str(listing_id or "").strip()
    catalog = str(
        values.get("manual_catalog_number") or ""
    ).strip()
    folded = fold_catalog(catalog)
    if not marketplace or not listing_id or not folded:
        return 0
    identification = {
        key: values.get(key)
        for key in (
            "manual_catalog_number",
            "manual_region",
            "manual_disc_count",
            "manual_pressing_type",
            "manual_media_type",
        )
        if values.get(key) not in {None, ""}
    }
    siblings = _catalog_sibling_copies(
        engine,
        account_id=account_id,
        folded_catalog=folded,
        marketplace=marketplace,
        listing_id=listing_id,
    )
    updated = 0
    for sibling in siblings:
        sibling_market = str(sibling["marketplace"] or "").strip()
        sibling_listing = str(sibling["listing_id"] or "").strip()
        if not sibling_market or not sibling_listing:
            continue
        if pressing_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        UPDATE warehouse.owned_copy
                        SET pressing_id = :pressing_id,
                            catalog_number = COALESCE(
                                NULLIF(btrim(catalog_number), ''),
                                :catalog_number
                            ),
                            updated_at = now()
                        WHERE account_id = CAST(:account_id AS uuid)
                          AND lower(btrim(source)) =
                              lower(btrim(:marketplace))
                          AND external_id::text =
                              CAST(:listing_id AS text)
                          AND (
                            pressing_id IS NULL
                            OR pressing_id = :pressing_id
                          )
                        """
                    ),
                    {
                        "account_id": account_id,
                        "marketplace": sibling_market,
                        "listing_id": sibling_listing,
                        "pressing_id": pressing_id,
                        "catalog_number": catalog,
                    },
                )
        if not ensure_anatomy_copy(
            engine,
            account_id=account_id,
            user_id=user_id,
            marketplace=sibling_market,
            listing_id=sibling_listing,
        ):
            continue
        if pressing_id is not None:
            assign_known_pressing(
                engine,
                marketplace=sibling_market,
                listing_id=sibling_listing,
                pressing_id=pressing_id,
                thumb_url=thumb_url,
            )
        if identification:
            updated += save_copy_anatomy(
                engine,
                account_id=account_id,
                user_id=user_id,
                marketplace=sibling_market,
                listing_id=sibling_listing,
                values=identification,
            )
        else:
            updated += 1
    return updated


def _catalog_sibling_copies(
    engine: Engine,
    *,
    account_id: str,
    folded_catalog: str,
    marketplace: str,
    listing_id: str,
) -> list[dict[str, Any]]:
    """Other purchased copies that print as the same catalog."""

    with engine.connect() as connection:
        rows = list(
            connection.execute(
                text(
                    """
                    SELECT
                        source AS marketplace,
                        external_id AS listing_id
                    FROM warehouse.owned_copy
                    WHERE account_id = CAST(:account_id AS uuid)
                      AND regexp_replace(
                        upper(coalesce(catalog_number, '')),
                        '[^A-Z0-9]',
                        '',
                        'g'
                      ) = :folded
                    UNION
                    SELECT
                        owned.marketplace::text AS marketplace,
                        owned.listing_id::text AS listing_id
                    FROM warehouse.auction_collector owned
                    LEFT JOIN warehouse.auction_collector_effective sale
                      ON sale.marketplace::text =
                         owned.marketplace::text
                     AND sale.listing_id::text =
                         owned.listing_id::text
                    WHERE owned.account_id = CAST(:account_id AS uuid)
                      AND owned.manual_purchased IS TRUE
                      AND regexp_replace(
                        upper(coalesce(
                            owned.manual_catalog_number,
                            sale.effective_catalog_number,
                            ''
                        )),
                        '[^A-Z0-9]',
                        '',
                        'g'
                      ) = :folded
                    """
                ),
                {
                    "account_id": account_id,
                    "folded": folded_catalog,
                },
            ).mappings()
        )
    source = (
        marketplace.casefold(),
        listing_id,
    )
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (
            str(row["marketplace"] or "").casefold(),
            str(row["listing_id"] or ""),
        )
        if key == source or not key[1] or key in seen:
            continue
        seen.add(key)
        found.append(dict(row))
    return found


@dataclass(frozen=True)
class CatalogIdentityGroup:
    """Copies that print as one catalog, ready to inherit or search Discogs."""

    folded: str
    catalog: str
    copies: tuple[tuple[str, str], ...]
    rows: tuple[dict[str, Any], ...]
    pressing_id: int | None
    thumb_url: str | None
    needs_search: bool
    donor: dict[str, Any] | None = None


def _copy_key(row: dict[str, Any]) -> tuple[str, str] | None:
    marketplace = str(row.get("marketplace") or "").strip().lower()
    listing_id = str(row.get("listing_id") or "").strip()
    if not marketplace or not listing_id or listing_id.casefold() in {"nan", "none"}:
        return None
    return marketplace, listing_id


def _row_catalog(row: dict[str, Any]) -> str:
    for field in ("manual_catalog_number", "catalog_number"):
        text = str(row.get(field) or "").strip()
        if text and text.casefold() not in {"nan", "none", "nat"}:
            return text
    return ""


def _row_pressing_id(row: dict[str, Any]) -> int | None:
    value = row.get("pressing_id")
    if value is None:
        return None
    try:
        if value != value:
            return None
    except Exception:
        pass
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def identity_values_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Catalog, region, discs, and media that siblings can inherit."""

    values: dict[str, Any] = {}
    catalog = _row_catalog(row)
    if catalog:
        values["manual_catalog_number"] = catalog
    region = str(row.get("manual_region") or row.get("region") or "").strip()
    if region and region.casefold() not in {"nan", "none"}:
        values["manual_region"] = region
    discs = row.get("manual_disc_count")
    if discs is None:
        discs = row.get("disc_count")
    try:
        if discs is not None and discs == discs:
            count = int(discs)
            if count > 0:
                values["manual_disc_count"] = count
    except (TypeError, ValueError):
        pass
    media = str(
        row.get("manual_media_type") or row.get("media_type") or ""
    ).strip()
    if media and media.casefold() not in {"nan", "none"}:
        values["manual_media_type"] = media
    pressing = str(row.get("manual_pressing_type") or "").strip()
    if pressing and pressing.casefold() not in {"nan", "none"}:
        values["manual_pressing_type"] = pressing
    return values


def catalog_identity_groups(
    rows: Sequence[dict[str, Any]],
) -> list[CatalogIdentityGroup]:
    """Group shelf copies by folded catalog. Bulk lots stay out."""

    buckets: dict[str, list[dict[str, Any]]] = {}
    catalogs: dict[str, str] = {}
    for row in rows:
        media = row.get("manual_media_type") or row.get("media_type")
        if collection_bulk_lot(media):
            continue
        if _copy_key(row) is None:
            continue
        catalog = _row_catalog(row)
        folded = fold_catalog(catalog)
        if not folded:
            continue
        buckets.setdefault(folded, []).append(row)
        catalogs.setdefault(folded, catalog)
    groups: list[CatalogIdentityGroup] = []
    for folded, copies in buckets.items():
        keys: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        identified: list[dict[str, Any]] = []
        pressing_ids: set[int] = set()
        for row in copies:
            key = _copy_key(row)
            if key is None or key in seen:
                continue
            seen.add(key)
            keys.append(key)
            pressing_id = _row_pressing_id(row)
            if pressing_id is not None:
                identified.append(row)
                pressing_ids.add(pressing_id)
        donor = identified[0] if len(pressing_ids) == 1 else None
        pressing_id = next(iter(pressing_ids)) if len(pressing_ids) == 1 else None
        groups.append(
            CatalogIdentityGroup(
                folded=folded,
                catalog=catalogs[folded],
                copies=tuple(keys),
                rows=tuple(copies),
                pressing_id=pressing_id,
                thumb_url=(
                    str(donor.get("discogs_thumb_url") or "").strip() or None
                    if donor
                    else None
                ),
                needs_search=pressing_id is None and len(pressing_ids) == 0,
                donor=donor,
            )
        )
    return groups


def unique_catalog_release_id(
    hits: Sequence[Any],
    *,
    catalog: str,
) -> int | None:
    """One Discogs release when every locking hit is the same id."""

    locked: set[int] = set()
    for hit in hits:
        catno = shortlist_field(hit, "catno")
        if not catno_locks_listing(
            str(catno) if catno is not None else None,
            catalog,
        ):
            continue
        release_id = shortlist_field(hit, "id", "discogs_id")
        try:
            locked.add(int(release_id))
        except (TypeError, ValueError):
            continue
    if len(locked) != 1:
        return None
    return next(iter(locked))


def fill_same_catalog_identities(
    engine: Engine,
    *,
    account_id: str,
    user_id: str,
    rows: Sequence[dict[str, Any]],
    client: Any = None,
    search_missing: bool = True,
) -> dict[str, int]:
    """Copy identity onto same-catalog siblings. Search Discogs once per leftover catalog."""

    stats = {
        "copied": 0,
        "searched": 0,
        "filled_search": 0,
        "skipped": 0,
    }
    for group in catalog_identity_groups(rows):
        if group.pressing_id is not None and group.donor is not None:
            values = identity_values_from_row(group.donor)
            donor_key = _copy_key(group.donor)
            for marketplace, listing_id in group.copies:
                if donor_key == (marketplace, listing_id):
                    continue
                if not ensure_anatomy_copy(
                    engine,
                    account_id=account_id,
                    user_id=user_id,
                    marketplace=marketplace,
                    listing_id=listing_id,
                ):
                    continue
                assign_known_pressing(
                    engine,
                    marketplace=marketplace,
                    listing_id=listing_id,
                    pressing_id=group.pressing_id,
                    thumb_url=group.thumb_url,
                )
                if values:
                    save_copy_anatomy(
                        engine,
                        account_id=account_id,
                        user_id=user_id,
                        marketplace=marketplace,
                        listing_id=listing_id,
                        values=values,
                    )
                stats["copied"] += 1
            continue
        if not group.needs_search or not search_missing or client is None:
            stats["skipped"] += 1
            continue
        first = group.rows[0]
        marketplace, listing_id = group.copies[0]
        try:
            hits = search_user_catalog(
                client,
                artist=str(first.get("artist_name") or "").strip() or None,
                title=str(
                    first.get("album_title") or first.get("listing_title") or ""
                ).strip()
                or None,
                query=group.catalog,
                listing_media=str(
                    first.get("manual_media_type") or first.get("media_type") or ""
                ).strip()
                or None,
            )
        except (DiscogsRateLimitError, DiscogsUnavailableError):
            stats["skipped"] += 1
            break
        stats["searched"] += 1
        release_id = unique_catalog_release_id(hits, catalog=group.catalog)
        if release_id is None:
            stats["skipped"] += 1
            continue
        if not ensure_anatomy_copy(
            engine,
            account_id=account_id,
            user_id=user_id,
            marketplace=marketplace,
            listing_id=listing_id,
        ):
            stats["skipped"] += 1
            continue
        try:
            applied = apply_release_choice(
                engine,
                marketplace=marketplace,
                listing_id=listing_id,
                release_id=release_id,
                client=client,
            )
        except (DiscogsRateLimitError, DiscogsUnavailableError):
            stats["skipped"] += 1
            break
        values = anatomy_values_from_choice(
            applied,
            printed_catalog=group.catalog,
        )
        save_copy_anatomy(
            engine,
            account_id=account_id,
            user_id=user_id,
            marketplace=marketplace,
            listing_id=listing_id,
            values=values,
        )
        propagate_catalog_identity_to_siblings(
            engine,
            account_id=account_id,
            user_id=user_id,
            marketplace=marketplace,
            listing_id=listing_id,
            values=values,
            pressing_id=applied.get("pressing_id"),
            thumb_url=applied.get("discogs_thumb_url"),
        )
        stats["filled_search"] += 1
    return stats


def apply_common_record_fields(
    engine: Engine,
    *,
    account_id: str,
    user_id: str,
    copies: list[tuple[str, str]] | tuple[tuple[str, str], ...],
    media_type: str | None,
    disc_count: int | None,
) -> int:
    """Write media type and disc count onto many copies. Grades stay."""

    values: dict[str, Any] = {}
    media = str(media_type or "").strip()
    if media and media not in {"Automatic / unset"}:
        values["manual_media_type"] = media
    if disc_count is not None:
        try:
            count = int(disc_count)
        except (TypeError, ValueError):
            count = 0
        if count > 0:
            values["manual_disc_count"] = count
    if not values:
        return 0
    updated = 0
    for marketplace, listing_id in copies:
        if not ensure_anatomy_copy(
            engine,
            account_id=account_id,
            user_id=user_id,
            marketplace=marketplace,
            listing_id=listing_id,
        ):
            continue
        updated += 1 if save_copy_anatomy(
            engine,
            account_id=account_id,
            user_id=user_id,
            marketplace=marketplace,
            listing_id=listing_id,
            values=values,
        ) else 0
    return updated


def save_copy_anatomy(
    engine: Engine,
    *,
    account_id: str,
    user_id: str,
    marketplace: str,
    listing_id: str,
    values: dict[str, Any],
) -> int:
    """Write Collector Review fields on a purchased copy. Item price stays."""

    marketplace = str(marketplace or "").strip()
    listing_id = str(listing_id or "").strip()
    if not marketplace or not listing_id:
        return 0
    allowed = {
        "manual_catalog_number",
        "manual_region",
        "manual_disc_count",
        "manual_pressing_type",
        "manual_media_type",
        "manual_condition_media",
        "manual_condition_cover",
        "manual_verdict",
        "manual_obi",
        "manual_insert_present",
        "manual_poster_present",
        "manual_sealed",
        "manual_rental",
        "manual_completeness_notes",
        "manual_collector_notes",
    }
    payload = {
        key: value
        for key, value in values.items()
        if key in allowed
    }
    if not payload:
        return 0
    assignments = [f"{key} = :{key}" for key in payload]
    assignments.append("updated_at = now()")
    parameters = {
        **payload,
        "account_id": account_id,
        "marketplace": marketplace,
        "listing_id": listing_id,
    }
    with account_transaction(
        engine,
        account_id=UUID(str(account_id)),
        user_id=UUID(str(user_id)),
    ) as connection:
        _promote_owned_copy(
            connection,
            account_id=account_id,
            marketplace=marketplace,
            listing_id=listing_id,
        )
        result = connection.execute(
            text(
                f"""
                UPDATE warehouse.auction_collector
                SET {", ".join(assignments)}
                WHERE account_id = CAST(:account_id AS uuid)
                  AND lower(btrim(marketplace::text)) =
                      lower(btrim(:marketplace))
                  AND listing_id::text = CAST(:listing_id AS text)
                  AND manual_purchased IS TRUE
                """
            ),
            parameters,
        )
        return max(result.rowcount or 0, 0)


def save_billing_note(
    engine: Engine,
    *,
    account_id: str,
    purchase: ParsedPurchase,
    marketplace: str = "",
    listing_id: str = "",
    user_id: str = "",
    persist_bill: bool = True,
) -> int:
    """Store the charge breakdown on a copy already on the shelf.

    The price printed on the item line replaces the shelf price. The
    order total does not. ``marketplace`` and ``listing_id`` name the
    shelf row when the bill itself has a different id. Returns how many
    rows were written.
    """

    note = purchase.billing_note.strip()
    if not note:
        return 0
    replace_price = line_price_replaces_shelf(purchase.paid_amount, note)
    marketplace = str(marketplace or "").strip()
    listing_id = str(listing_id or "").strip()
    if listing_id.lower() in {"nan", "none"}:
        listing_id = ""
    paid_on = purchase.paid_on
    delivered_on = purchase.delivered_on
    ensure_collection_bill_tables(engine)
    updated = 0

    def _run(connection) -> None:
        nonlocal updated
        nonlocal marketplace
        nonlocal listing_id

        if marketplace and listing_id:
            result = connection.execute(
                text(
                    """
                    UPDATE warehouse.auction_collector
                    SET manual_purchase_notes = :billing_note,
                        manual_purchase_price = CASE
                            WHEN :replace_price THEN :paid_amount
                            ELSE manual_purchase_price
                        END,
                        manual_purchase_date = COALESCE(
                            CAST(:paid_on AS date),
                            manual_purchase_date
                        ),
                        manual_delivered_on = COALESCE(
                            CAST(:delivered_on AS date),
                            manual_delivered_on
                        ),
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
                    "paid_amount": purchase.paid_amount,
                    "replace_price": replace_price,
                    "paid_on": paid_on,
                    "delivered_on": delivered_on,
                },
            )
            updated += max(result.rowcount or 0, 0)
            updated += _update_owned_copy_bill(
                connection,
                account_id=account_id,
                purchase=purchase,
                marketplace=marketplace,
                listing_id=listing_id,
                note=note,
                paid_on=paid_on,
            )
        if updated == 0 and purchase.source in {"ebay", "buyee", "recordcity"} and purchase.external_id:
            markets = (
                ("ebay", "gripsweat")
                if purchase.source == "ebay"
                else (purchase.source,)
            )
            for market in markets:
                result = connection.execute(
                    text(
                        """
                        UPDATE warehouse.auction_collector
                        SET manual_purchase_notes = :billing_note,
                            manual_purchase_price = CASE
                                WHEN :replace_price THEN :paid_amount
                                ELSE manual_purchase_price
                            END,
                            manual_purchase_date = COALESCE(
                                CAST(:paid_on AS date),
                                manual_purchase_date
                            ),
                            manual_delivered_on = COALESCE(
                                CAST(:delivered_on AS date),
                                manual_delivered_on
                            ),
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
                        "marketplace": market,
                        "listing_id": str(purchase.external_id).strip(),
                        "billing_note": note,
                        "paid_amount": purchase.paid_amount,
                        "replace_price": replace_price,
                        "paid_on": paid_on,
                        "delivered_on": delivered_on,
                    },
                )
                updated += max(result.rowcount or 0, 0)
                if updated:
                    marketplace = marketplace or market
                    listing_id = listing_id or str(purchase.external_id).strip()
                    break
        if updated and persist_bill:
            _write_saved_bill(
                connection,
                account_id=account_id,
                purchase=purchase,
                marketplace=marketplace,
                listing_id=listing_id,
                note=note,
            )
        if updated:
            _repair_chrome_listing_title(
                connection,
                marketplace=marketplace,
                listing_id=listing_id,
                title=purchase.title,
            )

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


def _bill_has_charges(note: str) -> bool:
    return any(
        value is not None
        for key, value in copy_costs(note).items()
        if key != "tax_included"
    )


def _note_charge_totals(note: str) -> tuple[Decimal, Decimal, Decimal]:
    costs = copy_costs(note)
    shipping = (costs["shipping"] or Decimal("0")) + (
        costs["domestic_shipping"] or Decimal("0")
    )
    tax = (costs["tax"] or Decimal("0")) + (costs["customs"] or Decimal("0"))
    fees = (
        (costs["plan_fee"] or Decimal("0"))
        + (costs["service_fee"] or Decimal("0"))
        + (costs["clearance"] or Decimal("0"))
    )
    return shipping, tax, fees


def bill_copy_identity(
    marketplace: str,
    listing_id: str,
    purchase: ParsedPurchase,
) -> tuple[str, str]:
    """Shelf listing id, or the shop auction id when this copy was never scraped."""

    market = str(marketplace or purchase.source or "").strip()
    listing = str(listing_id or purchase.external_id or "").strip()
    return market, listing


def save_package_bill(
    engine: Engine,
    *,
    account_id: str,
    copies: list[tuple[str, str, ParsedPurchase]],
    user_id: str = "",
) -> int:
    """Write one combined order: totals card on the bill, share on each line."""

    if not copies:
        return 0
    first = copies[0][2]
    source = str(first.source or "typed").strip().lower()
    if source not in {"ebay", "buyee", "discogs"}:
        source = "typed"
    currency = (
        copy_cost_currency(first.billing_note) or first.paid_currency or "USD"
    ).upper()
    lines = [
        _bill_line_for_copy(marketplace, listing_id, purchase)
        for marketplace, listing_id, purchase in copies
        if marketplace and listing_id
    ]
    if not lines:
        return 0
    order_id = str(first.order_id or "").strip() or None
    if not order_id:
        ids = sorted(
            {
                str(listing_id).strip()
                for _market, listing_id, _purchase in copies
                if str(listing_id or "").strip()
            }
        )
        if len(ids) >= 2:
            order_id = "package:" + "+".join(ids)
    raw_note = _package_card_note(first, currency)
    billed_on = next(
        (purchase.paid_on for _market, _listing, purchase in copies if purchase.paid_on),
        first.paid_on,
    )
    bill, written = package_bill_from_copies(
        account_id=str(account_id),
        source=source,
        order_id=order_id,
        currency=currency,
        package_item=first.package_item,
        package_shipping=first.package_shipping,
        package_tax=first.package_tax,
        package_total=first.package_total,
        raw_note=raw_note,
        billed_on=billed_on,
        lines=lines,
    )
    ensure_collection_bill_tables(engine)

    def _run(connection) -> int:
        return write_collection_bill(
            connection,
            account_id=str(account_id),
            source=str(bill["source"]),
            external_order_id=bill["external_order_id"],
            currency=str(bill["currency"]),
            item_total=bill["item_total"],
            shipping_total=bill["shipping_total"],
            tax_total=bill["tax_total"],
            fee_total=bill["fee_total"],
            grand_total=bill["grand_total"],
            raw_note=str(bill["raw_note"]),
            fulfillment_status=bill["fulfillment_status"],
            lines=written,
            billed_on=billed_on,
        )

    if user_id:
        with account_transaction(
            engine,
            account_id=UUID(str(account_id)),
            user_id=UUID(str(user_id)),
        ) as connection:
            return _run(connection)
    with engine.begin() as connection:
        return _run(connection)


def _bill_line_for_copy(
    marketplace: str,
    listing_id: str,
    purchase: ParsedPurchase,
) -> BillLine:
    note = purchase.billing_note.strip()
    shipping, tax, fees = _note_charge_totals(note)
    return BillLine(
        marketplace=str(marketplace).strip(),
        listing_id=str(listing_id).strip(),
        printed_id=str(purchase.external_id or "").strip(),
        item_amount=purchase.paid_amount or Decimal("0"),
        shipping_amount=shipping,
        tax_amount=tax,
        fee_amount=fees,
        line_note=note,
    )


def _package_card_note(purchase: ParsedPurchase, currency: str) -> str:
    if (
        purchase.package_item is None
        and purchase.package_shipping is None
        and purchase.package_tax is None
        and purchase.package_total is None
    ):
        return purchase.billing_note.strip()
    parts = []
    if purchase.package_item is not None:
        parts.append(f"Items {purchase.package_item} {currency}")
    if purchase.package_shipping is not None:
        parts.append(f"Shipping {purchase.package_shipping} {currency}")
    if purchase.package_tax is not None:
        parts.append(f"Tax {purchase.package_tax} {currency}")
    if purchase.package_total is not None:
        parts.append(f"Order total {purchase.package_total} {currency}")
    if purchase.order_id:
        parts.append(f"Order {purchase.order_id}")
    return "\n".join(parts) or purchase.billing_note.strip()


def _write_saved_bill(
    connection: Any,
    *,
    account_id: str,
    purchase: ParsedPurchase,
    marketplace: str,
    listing_id: str,
    note: str,
) -> None:
    line_market = str(marketplace or purchase.source or "").strip()
    line_id = str(listing_id or purchase.external_id or "").strip()
    if not line_market or not line_id:
        return
    shipping, tax, fees = _note_charge_totals(note)
    item = purchase.paid_amount or Decimal("0")
    source = str(purchase.source or "typed").strip().lower()
    if source not in {"ebay", "buyee", "discogs"}:
        source = "typed"
    printed = str(purchase.external_id or "").strip()
    order_id = None
    if source != "typed" and printed and not printed.startswith("log:"):
        order_id = printed
    currency = (copy_cost_currency(note) or purchase.paid_currency or "USD").upper()
    write_collection_bill(
        connection,
        account_id=str(account_id),
        source=source,
        external_order_id=order_id,
        currency=currency,
        item_total=item,
        shipping_total=shipping,
        tax_total=tax,
        fee_total=fees,
        grand_total=item + shipping + tax + fees,
        raw_note=note,
        fulfillment_status=None,
        lines=[
            BillLine(
                marketplace=line_market,
                listing_id=line_id,
                printed_id=printed,
                item_amount=item,
                shipping_amount=shipping,
                tax_amount=tax,
                fee_amount=fees,
                line_note=note,
            )
        ],
        billed_on=purchase.paid_on,
    )


def _owned_copy_values(
    purchase: ParsedPurchase,
    *,
    catalog_number: str = "",
    paid_amount: Decimal | None = None,
    current_title: object = None,
    current_catalog: object = None,
    current_paid: object = None,
) -> tuple[str, str | None, Decimal | None]:
    """Title, catalog, and item for an owned_copy row. OCR stew is not kept."""

    incoming_title = str(purchase.title or "").strip()
    if listing_title_is_ocr_junk(incoming_title):
        incoming_title = ""
    current = str(current_title or "").strip()
    current_is_junk = listing_title_is_ocr_junk(current)
    if incoming_title:
        title = incoming_title
    elif current_is_junk:
        title = ""
    else:
        title = current

    incoming_catalog = str(catalog_number or purchase.catalog_number or "").strip()
    if listing_title_is_ocr_junk(str(purchase.title or "")) and not str(
        catalog_number or ""
    ).strip():
        incoming_catalog = (
            incoming_catalog
            if listing_catalog_is_structured(incoming_catalog)
            else ""
        )
    stored_catalog = str(current_catalog or "").strip()
    if incoming_catalog:
        catalog: str | None = incoming_catalog
    elif listing_catalog_is_structured(stored_catalog):
        catalog = stored_catalog
    elif current_is_junk:
        catalog = None
    else:
        catalog = stored_catalog or None

    paid = paid_amount if paid_amount is not None else purchase.paid_amount
    if current_paid is not None and paid is None:
        try:
            paid = Decimal(str(current_paid))
        except InvalidOperation:
            paid = None
    recovered = ocr_promo_item_price(purchase.title, paid)
    if recovered is None:
        recovered = ocr_promo_item_price(current, paid)
    if recovered is not None:
        paid = recovered
    elif current_is_junk and purchase.paid_amount is not None:
        paid = purchase.paid_amount
    return title, catalog, paid


def _update_owned_copy_bill(
    connection: Any,
    *,
    account_id: str,
    purchase: ParsedPurchase,
    marketplace: str,
    listing_id: str,
    note: str,
    paid_on: date | None,
) -> int:
    """Write the bill onto owned_copy and repair a $100 OCR promo item."""

    current = connection.execute(
        text(
            """
            SELECT title, catalog_number, paid_amount
            FROM warehouse.owned_copy
            WHERE account_id = CAST(:account_id AS uuid)
              AND lower(btrim(source)) = lower(btrim(:marketplace))
              AND external_id::text = CAST(:listing_id AS text)
            """
        ),
        {
            "account_id": account_id,
            "marketplace": marketplace,
            "listing_id": listing_id,
        },
    ).mappings().first()
    if current is None:
        return 0
    title, catalog, paid = _owned_copy_values(
        purchase,
        paid_amount=purchase.paid_amount,
        current_title=current["title"],
        current_catalog=current["catalog_number"],
        current_paid=current["paid_amount"],
    )
    result = connection.execute(
        text(
            """
            UPDATE warehouse.owned_copy
            SET billing_note = :billing_note,
                paid_on = COALESCE(CAST(:paid_on AS date), paid_on),
                delivered_on = COALESCE(CAST(:delivered_on AS date), delivered_on),
                title = :title,
                catalog_number = :catalog_number,
                paid_amount = COALESCE(:paid_amount, paid_amount),
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
            "paid_on": paid_on,
            "delivered_on": purchase.delivered_on,
            "title": title,
            "catalog_number": catalog,
            "paid_amount": paid,
        },
    )
    return max(result.rowcount or 0, 0)


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
        current = connection.execute(
            text(
                """
                SELECT title, catalog_number, paid_amount
                FROM warehouse.owned_copy
                WHERE account_id = CAST(:account_id AS uuid)
                  AND source = :source
                  AND external_id = :external_id
                """
            ),
            {
                "account_id": account_id,
                "source": purchase.source,
                "external_id": purchase.external_id,
            },
        ).mappings().first()
        title, stored_catalog, stored_paid = _owned_copy_values(
            purchase,
            catalog_number=catalog_number,
            paid_amount=paid_amount,
            current_title=None if current is None else current["title"],
            current_catalog=None if current is None else current["catalog_number"],
            current_paid=None if current is None else current["paid_amount"],
        )
        sale_type = default_sale_type(purchase.source)
        delivered_on = default_delivered_on(
            purchase.source,
            paid_on or purchase.paid_on,
            purchase.delivered_on,
        )
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
                    delivered_on,
                    sale_type,
                    billing_note,
                    media_type
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
                    :delivered_on,
                    NULLIF(:sale_type, ''),
                    :billing_note,
                    :media_type
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
                    delivered_on = COALESCE(
                        EXCLUDED.delivered_on,
                        warehouse.owned_copy.delivered_on
                    ),
                    sale_type = COALESCE(
                        EXCLUDED.sale_type,
                        warehouse.owned_copy.sale_type
                    ),
                    billing_note = EXCLUDED.billing_note,
                    media_type = COALESCE(
                        EXCLUDED.media_type,
                        warehouse.owned_copy.media_type
                    ),
                    updated_at = now()
                """
            ),
            {
                "account_id": account_id,
                "source": purchase.source,
                "external_id": purchase.external_id,
                "title": title,
                "seller": purchase.seller,
                "catalog_number": stored_catalog,
                "pressing_id": pressing_id,
                "paid_amount": stored_paid,
                "paid_currency": paid_currency or None,
                "paid_on": paid_on,
                "delivered_on": delivered_on,
                "sale_type": sale_type,
                "billing_note": purchase.billing_note or "",
                "media_type": purchase_media(title, purchase.billing_note) or None,
            },
        )


def stamp_owned_lot(
    engine: Engine,
    *,
    source: str,
    paid_on: date,
    delivered_on: date,
    sale_type: str,
) -> int:
    """Write one order date's delivery and sale type onto every copy in that lot."""

    code = sale_type_code(sale_type) or default_sale_type(source)
    with engine.begin() as connection:
        result = connection.execute(
            text(
                """
                UPDATE warehouse.owned_copy
                SET delivered_on = COALESCE(
                        delivered_on,
                        CAST(:delivered_on AS date)
                    ),
                    sale_type = COALESCE(
                        NULLIF(sale_type, ''),
                        NULLIF(:sale_type, '')
                    ),
                    updated_at = now()
                WHERE lower(btrim(source)) = lower(btrim(:source))
                  AND paid_on = CAST(:paid_on AS date)
                """
            ),
            {
                "source": source,
                "paid_on": paid_on,
                "delivered_on": delivered_on,
                "sale_type": code,
            },
        )
        return max(result.rowcount or 0, 0)


def stamp_source_sale_type(engine: Engine, source: str, sale_type: str) -> int:
    """Fill unlabeled copies from one shop with that shop's default sale type."""

    code = sale_type_code(sale_type) or default_sale_type(source)
    if not code:
        return 0
    with engine.begin() as connection:
        result = connection.execute(
            text(
                """
                UPDATE warehouse.owned_copy
                SET sale_type = :sale_type,
                    updated_at = now()
                WHERE lower(btrim(source)) = lower(btrim(:source))
                  AND NULLIF(btrim(sale_type), '') IS NULL
                """
            ),
            {"source": source, "sale_type": code},
        )
        return max(result.rowcount or 0, 0)


def attach_unique_owned_pressings(engine: Engine) -> int:
    """Attach the only pressing for a catalog when the owned copy has none."""

    updated = 0
    with engine.begin() as connection:
        copies = list(
            connection.execute(
                text(
                    """
                    SELECT id, catalog_number
                    FROM warehouse.owned_copy
                    WHERE pressing_id IS NULL
                      AND NULLIF(btrim(catalog_number), '') IS NOT NULL
                    """
                )
            ).mappings()
        )
        pressings = list(
            connection.execute(
                text(
                    """
                    SELECT
                        pressing.id AS pressing_id,
                        pressing.catalog_number,
                        COALESCE(family.display_artist, '') AS artist_name,
                        COALESCE(family.display_title, '') AS album_title,
                        COALESCE(pressing.media_type, '') AS media_type
                    FROM warehouse.pressing_identity pressing
                    LEFT JOIN warehouse.release_family family
                      ON family.id = pressing.release_family_id
                    """
                )
            ).mappings()
        )
        grouped: dict[str, list[PressingChoice]] = {}
        for row in pressings:
            catalog = str(row["catalog_number"] or "")
            folded = fold_catalog(catalog)
            if not folded:
                continue
            grouped.setdefault(folded, []).append(
                PressingChoice(
                    pressing_id=int(row["pressing_id"]),
                    catalog_number=catalog,
                    artist_name=str(row["artist_name"] or ""),
                    album_title=str(row["album_title"] or ""),
                )
            )
        for copy in copies:
            catalog = str(copy["catalog_number"] or "")
            dummy = ParsedPurchase(
                source="buyee",
                external_id=str(copy["id"]),
                title="",
                seller="",
                paid_amount=None,
                paid_currency="JPY",
                paid_on=None,
                catalog_number=catalog,
            )
            choices = tuple(grouped.get(fold_catalog(catalog), ()))
            picked = _single_bill_pressing(dummy, choices)
            if len(picked) != 1:
                continue
            result = connection.execute(
                text(
                    """
                    UPDATE warehouse.owned_copy
                    SET pressing_id = :pressing_id,
                        catalog_number = COALESCE(
                            NULLIF(btrim(catalog_number), ''),
                            :catalog_number
                        ),
                        updated_at = now()
                    WHERE id = :id
                      AND pressing_id IS NULL
                    """
                ),
                {
                    "id": copy["id"],
                    "pressing_id": picked[0].pressing_id,
                    "catalog_number": picked[0].catalog_number,
                },
            )
            updated += max(result.rowcount or 0, 0)
    return updated


def _shelf_markets(marketplace: str) -> tuple[str, ...]:
    market = str(marketplace or "").strip().lower()
    if market in {"ebay", "gripsweat"}:
        return ("ebay", "gripsweat")
    return (market,) if market else ()


def save_shelf_facts(
    engine: Engine,
    *,
    account_id: str,
    marketplace: str,
    listing_id: str,
    paid_amount: Decimal | None,
    paid_on: date | None,
    delivered_on: date | None,
    sale_type: str,
) -> int:
    """Write paid, delivered, item, and sale type onto the shelf copy."""

    market = str(marketplace or "").strip()
    listing = str(listing_id or "").strip()
    if not market or not listing:
        return 0
    code = sale_type_code(sale_type)
    updated = 0
    with engine.begin() as connection:
        collector = connection.execute(
            text(
                """
                UPDATE warehouse.auction_collector
                SET manual_purchase_price = COALESCE(
                        :paid_amount,
                        manual_purchase_price
                    ),
                    manual_purchase_date = CAST(:paid_on AS date),
                    manual_delivered_on = CAST(:delivered_on AS date),
                    manual_auction_format = NULLIF(:sale_type, ''),
                    purchase_updated_at = now(),
                    updated_at = now()
                WHERE account_id = CAST(:account_id AS uuid)
                  AND lower(btrim(marketplace::text)) = lower(btrim(:marketplace))
                  AND listing_id::text = CAST(:listing_id AS text)
                  AND manual_purchased IS TRUE
                """
            ),
            {
                "account_id": account_id,
                "marketplace": market,
                "listing_id": listing,
                "paid_amount": paid_amount,
                "paid_on": paid_on,
                "delivered_on": delivered_on,
                "sale_type": code,
            },
        )
        updated += max(collector.rowcount or 0, 0)
        owned = connection.execute(
            text(
                """
                UPDATE warehouse.owned_copy
                SET paid_amount = COALESCE(:paid_amount, paid_amount),
                    paid_on = CAST(:paid_on AS date),
                    delivered_on = CAST(:delivered_on AS date),
                    sale_type = NULLIF(:sale_type, ''),
                    updated_at = now()
                WHERE account_id = CAST(:account_id AS uuid)
                  AND lower(btrim(source)) = lower(btrim(:marketplace))
                  AND external_id::text = CAST(:listing_id AS text)
                """
            ),
            {
                "account_id": account_id,
                "marketplace": market,
                "listing_id": listing,
                "paid_amount": paid_amount,
                "paid_on": paid_on,
                "delivered_on": delivered_on,
                "sale_type": code,
            },
        )
        updated += max(owned.rowcount or 0, 0)
    return updated


@dataclass(frozen=True)
class LotCopy:
    """One shelf copy, grouped with the others from the same order."""

    marketplace: str
    listing_id: str
    order_id: str
    paid_on: date | None
    delivered_on: date | None


def _lot_day(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def lot_package_id(listing_ids: Sequence[str]) -> str:
    """Stable package id for one Buyee order's auction ids."""

    ids = sorted(
        {
            str(listing_id).strip().lower()
            for listing_id in listing_ids
            if str(listing_id or "").strip()
        }
    )
    return "package:" + "+".join(ids)


def backfill_lot_paid_on(
    engine: Engine,
    *,
    account_id: str,
    marketplace: str,
    listing_ids: Sequence[str],
    paid_on: date,
    package_shipping: Decimal | None = None,
    package_tax: Decimal | None = None,
    package_total: Decimal | None = None,
) -> int:
    """Write one paid-on date onto every copy in a lot, and onto the bill.

    Delivery dates stay as they are. Copies that were never saved as a
    combined order get a package bill so they group together afterward.
    """

    ids = [
        str(listing_id).strip()
        for listing_id in listing_ids
        if str(listing_id or "").strip()
    ]
    if not ids or paid_on is None:
        return 0
    market = str(marketplace or "").strip().lower()
    account = str(account_id)
    wrote = 0
    with engine.begin() as connection:
        for listing_id in ids:
            collector = connection.execute(
                text(
                    """
                    UPDATE warehouse.auction_collector
                    SET manual_purchase_date = CAST(:paid_on AS date),
                        purchase_updated_at = now(),
                        updated_at = now()
                    WHERE account_id = CAST(:account_id AS uuid)
                      AND lower(btrim(marketplace::text)) = lower(btrim(:marketplace))
                      AND listing_id::text = CAST(:listing_id AS text)
                      AND manual_purchased IS TRUE
                    """
                ),
                {
                    "account_id": account,
                    "marketplace": market,
                    "listing_id": listing_id,
                    "paid_on": paid_on,
                },
            )
            owned = connection.execute(
                text(
                    """
                    UPDATE warehouse.owned_copy
                    SET paid_on = CAST(:paid_on AS date),
                        updated_at = now()
                    WHERE account_id = CAST(:account_id AS uuid)
                      AND lower(btrim(source)) = lower(btrim(:marketplace))
                      AND external_id::text = CAST(:listing_id AS text)
                    """
                ),
                {
                    "account_id": account,
                    "marketplace": market,
                    "listing_id": listing_id,
                    "paid_on": paid_on,
                },
            )
            wrote += max(collector.rowcount or 0, 0) + max(owned.rowcount or 0, 0)
        billed = connection.execute(
            text(
                """
                UPDATE warehouse.collection_bill header
                SET billed_on = CAST(:paid_on AS date),
                    updated_at = now()
                WHERE header.account_id = CAST(:account_id AS uuid)
                  AND header.id IN (
                    SELECT DISTINCT line.bill_id
                    FROM warehouse.collection_bill_line line
                    WHERE line.account_id = CAST(:account_id AS uuid)
                      AND lower(btrim(line.marketplace)) = lower(btrim(:marketplace))
                      AND line.listing_id = ANY(:ids)
                  )
                """
            ),
            {
                "account_id": account,
                "marketplace": market,
                "paid_on": paid_on,
                "ids": ids,
            },
        )
        if (billed.rowcount or 0) > 0:
            return wrote
        rows = connection.execute(
            text(
                """
                SELECT external_id, paid_amount, COALESCE(billing_note, '') AS note
                FROM warehouse.owned_copy
                WHERE account_id = CAST(:account_id AS uuid)
                  AND lower(btrim(source)) = lower(btrim(:marketplace))
                  AND external_id = ANY(:ids)
                """
            ),
            {"account_id": account, "marketplace": market, "ids": ids},
        ).mappings()
        lines = [
            BillLine(
                market,
                str(row["external_id"]),
                str(row["external_id"]),
                row["paid_amount"] or Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                str(row["note"] or ""),
            )
            for row in rows
        ]
        if not lines:
            return wrote
        item_total = sum((line.item_amount for line in lines), Decimal("0"))
        bill, written = package_bill_from_copies(
            account_id=account,
            source=market,
            order_id=lot_package_id(ids),
            currency="JPY",
            package_item=item_total,
            package_shipping=package_shipping,
            package_tax=package_tax,
            package_total=package_total,
            raw_note=(
                f"Items {item_total} JPY\n"
                f"Shipping {package_shipping or 0} JPY\n"
                f"Tax {package_tax or 0} JPY\n"
                f"Order total {package_total or item_total} JPY"
            ),
            billed_on=paid_on,
            lines=lines,
        )
        write_collection_bill(
            connection,
            account_id=account,
            source=str(bill["source"]),
            external_order_id=bill["external_order_id"],
            currency=str(bill["currency"]),
            item_total=bill["item_total"],
            shipping_total=bill["shipping_total"],
            tax_total=bill["tax_total"],
            fee_total=bill["fee_total"],
            grand_total=bill["grand_total"],
            raw_note=str(bill["raw_note"]),
            fulfillment_status=bill["fulfillment_status"],
            lines=written,
            billed_on=paid_on,
        )
    return wrote


def stamp_lot_dates(
    copies: Sequence[LotCopy],
    *,
    paid_on: date | None,
    delivered_on: date | None = None,
    selected_ids: Sequence[str] | None = None,
    explicit: bool = False,
) -> list[LotCopy]:
    """Put one order date on the whole lot unless the user named a subset."""

    if paid_on is None and delivered_on is None:
        return []
    wanted = {str(listing_id).strip() for listing_id in (selected_ids or ()) if listing_id}
    if not explicit or not wanted:
        wanted = {str(copy.listing_id).strip() for copy in copies if copy.listing_id}
    stamped: list[LotCopy] = []
    for copy in copies:
        listing_id = str(copy.listing_id or "").strip()
        if listing_id not in wanted:
            continue
        if copy.paid_on == paid_on and copy.delivered_on == delivered_on:
            continue
        stamped.append(replace(copy, paid_on=paid_on, delivered_on=delivered_on))
    return stamped


def lot_date_updates(
    copies: Sequence[LotCopy],
    *,
    billed_on_by_order: dict[str, date] | None = None,
) -> list[LotCopy]:
    """Fill a lot from the copy that already has the shared dates.

    One order is one payment and one delivery. A paid-on date on any copy
    of the order is the order date for the rest, even before anything is
    delivered. When no copy is dated yet, the bill's billed-on date is the
    order date. When the copies that already have a delivery date agree, the
    rest of that order takes that delivery date and that order date. A copy
    that already has its own delivery date stays as it is. Copies from
    different orders stay apart.
    """

    grouped: dict[str, list[LotCopy]] = {}
    for copy in copies:
        order_id = str(copy.order_id or "").strip()
        if not order_id:
            continue
        paid_on = _lot_day(copy.paid_on)
        delivered_on = _lot_day(copy.delivered_on)
        grouped.setdefault(order_id, []).append(
            replace(
                copy,
                marketplace=str(copy.marketplace or "").strip(),
                listing_id=str(copy.listing_id or "").strip(),
                order_id=order_id,
                paid_on=paid_on,
                delivered_on=delivered_on,
            )
        )
    updates: list[LotCopy] = []
    for group in grouped.values():
        delivered = [copy for copy in group if copy.delivered_on is not None]
        if delivered:
            delivery_dates = {copy.delivered_on for copy in delivered}
            if len(delivery_dates) != 1:
                continue
            delivered_on = next(iter(delivery_dates))
            paid_dates = {copy.paid_on for copy in delivered if copy.paid_on is not None}
            shared_paid = next(iter(paid_dates)) if len(paid_dates) == 1 else None
            for copy in group:
                if not copy.marketplace or not copy.listing_id:
                    continue
                if copy.delivered_on is not None:
                    continue
                paid_on = shared_paid if shared_paid is not None else copy.paid_on
                if paid_on == copy.paid_on and delivered_on == copy.delivered_on:
                    continue
                updates.append(
                    replace(copy, paid_on=paid_on, delivered_on=delivered_on)
                )
            continue
        paid_dates = {copy.paid_on for copy in group if copy.paid_on is not None}
        shared_paid = next(iter(paid_dates)) if len(paid_dates) == 1 else None
        if shared_paid is None:
            billed = (billed_on_by_order or {}).get(group[0].order_id)
            shared_paid = _lot_day(billed)
        if shared_paid is None:
            continue
        for copy in group:
            if not copy.marketplace or not copy.listing_id:
                continue
            if copy.paid_on == shared_paid:
                continue
            updates.append(replace(copy, paid_on=shared_paid))
    return updates


def inherit_lot_dates(
    purchases: Sequence[ParsedPurchase],
) -> tuple[ParsedPurchase, ...]:
    """Give every copy in an incoming order the shared paid-on and delivery dates."""

    copies = [
        LotCopy(
            marketplace=purchase.source,
            listing_id=purchase.external_id,
            order_id=purchase.order_id,
            paid_on=purchase.paid_on,
            delivered_on=purchase.delivered_on,
        )
        for purchase in purchases
    ]
    updates = {
        (copy.marketplace.lower(), copy.listing_id): copy
        for copy in lot_date_updates(copies)
    }
    if not updates:
        return tuple(purchases)
    inherited: list[ParsedPurchase] = []
    for purchase in purchases:
        identity = (
            str(purchase.source or "").strip().lower(),
            str(purchase.external_id or "").strip(),
        )
        update = updates.get(identity)
        if update is None:
            inherited.append(purchase)
            continue
        inherited.append(
            replace(
                purchase,
                paid_on=update.paid_on,
                delivered_on=update.delivered_on,
            )
        )
    return tuple(inherited)


def purchases_with_lot_paid_on(
    purchases: Sequence[ParsedPurchase],
    *,
    paid_on: date | None,
) -> tuple[ParsedPurchase, ...]:
    """Put one order date on every copy in the incoming lot."""

    inherited = inherit_lot_dates(purchases)
    if paid_on is None:
        return inherited
    return tuple(replace(purchase, paid_on=paid_on) for purchase in inherited)


def align_lot_dates(engine: Engine, *, account_id: str) -> int:
    """Write a delivered copy's order date and delivery date onto the rest of its order."""

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT
                    lower(btrim(owned.marketplace::text)) AS marketplace,
                    owned.listing_id::text AS listing_id,
                    owned.manual_purchase_date AS paid_on,
                    owned.manual_delivered_on AS delivered_on,
                    bill.order_id,
                    bill.billed_on
                FROM warehouse.auction_collector owned
                LEFT JOIN LATERAL (
                    SELECT header.external_order_id AS order_id,
                           header.billed_on
                    FROM warehouse.collection_bill_line line
                    JOIN warehouse.collection_bill header
                      ON header.id = line.bill_id
                    WHERE line.account_id = owned.account_id
                      AND lower(btrim(line.marketplace)) =
                          lower(btrim(owned.marketplace::text))
                      AND line.listing_id = owned.listing_id::text
                    ORDER BY line.created_at DESC
                    LIMIT 1
                ) bill ON TRUE
                WHERE owned.account_id = CAST(:account_id AS uuid)
                  AND owned.manual_purchased IS TRUE
                  AND NULLIF(btrim(bill.order_id), '') IS NOT NULL
                UNION ALL
                SELECT
                    lower(btrim(owned.source)) AS marketplace,
                    owned.external_id AS listing_id,
                    owned.paid_on,
                    owned.delivered_on,
                    bill.order_id,
                    bill.billed_on
                FROM warehouse.owned_copy owned
                LEFT JOIN LATERAL (
                    SELECT header.external_order_id AS order_id,
                           header.billed_on
                    FROM warehouse.collection_bill_line line
                    JOIN warehouse.collection_bill header
                      ON header.id = line.bill_id
                    WHERE line.account_id = owned.account_id
                      AND lower(btrim(line.marketplace)) = lower(btrim(owned.source))
                      AND line.listing_id = owned.external_id::text
                    ORDER BY line.created_at DESC
                    LIMIT 1
                ) bill ON TRUE
                WHERE owned.account_id = CAST(:account_id AS uuid)
                  AND NULLIF(btrim(bill.order_id), '') IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1
                    FROM warehouse.auction_collector collector
                    WHERE collector.account_id = owned.account_id
                      AND lower(btrim(collector.marketplace::text)) =
                          lower(btrim(owned.source))
                      AND collector.listing_id::text = owned.external_id::text
                      AND collector.manual_purchased IS TRUE
                  )
                """
            ),
            {"account_id": account_id},
        ).mappings()
        records = list(rows)
        copies = [
            LotCopy(
                marketplace=str(row["marketplace"] or ""),
                listing_id=str(row["listing_id"] or ""),
                order_id=str(row["order_id"] or ""),
                paid_on=row["paid_on"],
                delivered_on=row["delivered_on"],
            )
            for row in records
        ]
        billed_on_by_order: dict[str, date] = {}
        for row in records:
            billed = _lot_day(row["billed_on"])
            order_id = str(row["order_id"] or "").strip()
            if billed is None or not order_id or order_id in billed_on_by_order:
                continue
            billed_on_by_order[order_id] = billed
    wrote = 0
    for copy in lot_date_updates(
        copies, billed_on_by_order=billed_on_by_order
    ):
        wrote += save_shelf_dates(
            engine,
            account_id=account_id,
            marketplace=copy.marketplace,
            listing_id=copy.listing_id,
            paid_on=copy.paid_on,
            delivered_on=copy.delivered_on,
        )
    return wrote


def save_shelf_dates(
    engine: Engine,
    *,
    account_id: str,
    marketplace: str,
    listing_id: str,
    paid_on: date | None,
    delivered_on: date | None,
) -> int:
    """Write the order date and delivery date. Item price and sale type stay."""

    market = str(marketplace or "").strip()
    listing = str(listing_id or "").strip()
    if not market or not listing:
        return 0
    updated = 0
    with engine.begin() as connection:
        collector = connection.execute(
            text(
                """
                UPDATE warehouse.auction_collector
                SET manual_purchase_date = CAST(:paid_on AS date),
                    manual_delivered_on = CAST(:delivered_on AS date),
                    purchase_updated_at = now(),
                    updated_at = now()
                WHERE account_id = CAST(:account_id AS uuid)
                  AND lower(btrim(marketplace::text)) = lower(btrim(:marketplace))
                  AND listing_id::text = CAST(:listing_id AS text)
                  AND manual_purchased IS TRUE
                """
            ),
            {
                "account_id": account_id,
                "marketplace": market,
                "listing_id": listing,
                "paid_on": paid_on,
                "delivered_on": delivered_on,
            },
        )
        updated += max(collector.rowcount or 0, 0)
        owned = connection.execute(
            text(
                """
                UPDATE warehouse.owned_copy
                SET paid_on = CAST(:paid_on AS date),
                    delivered_on = CAST(:delivered_on AS date),
                    updated_at = now()
                WHERE account_id = CAST(:account_id AS uuid)
                  AND lower(btrim(source)) = lower(btrim(:marketplace))
                  AND external_id::text = CAST(:listing_id AS text)
                """
            ),
            {
                "account_id": account_id,
                "marketplace": market,
                "listing_id": listing,
                "paid_on": paid_on,
                "delivered_on": delivered_on,
            },
        )
        updated += max(owned.rowcount or 0, 0)
    return updated


def remove_shelf_copy(
    engine: Engine,
    *,
    account_id: str,
    marketplace: str,
    listing_id: str,
) -> int:
    """Take one copy off My Collection. The marketplace listing stays."""

    listing = str(listing_id or "").strip()
    markets = _shelf_markets(marketplace)
    if not listing or not markets:
        return 0
    removed = 0
    with engine.begin() as connection:
        collector = connection.execute(
            text(
                """
                UPDATE warehouse.auction_collector
                SET manual_purchased = FALSE,
                    purchase_updated_at = now(),
                    updated_at = now()
                WHERE account_id = CAST(:account_id AS uuid)
                  AND lower(btrim(marketplace::text)) = ANY(:markets)
                  AND listing_id::text = CAST(:listing_id AS text)
                  AND manual_purchased IS TRUE
                """
            ),
            {
                "account_id": account_id,
                "markets": list(markets),
                "listing_id": listing,
            },
        )
        removed += max(collector.rowcount or 0, 0)
        owned = connection.execute(
            text(
                """
                DELETE FROM warehouse.owned_copy
                WHERE account_id = CAST(:account_id AS uuid)
                  AND lower(btrim(source)) = ANY(:markets)
                  AND external_id::text = CAST(:listing_id AS text)
                """
            ),
            {
                "account_id": account_id,
                "markets": list(markets),
                "listing_id": listing,
            },
        )
        removed += max(owned.rowcount or 0, 0)
        connection.execute(
            text(
                """
                DELETE FROM warehouse.collection_bill_line
                WHERE account_id = CAST(:account_id AS uuid)
                  AND lower(btrim(marketplace)) = ANY(:markets)
                  AND listing_id = CAST(:listing_id AS text)
                """
            ),
            {
                "account_id": account_id,
                "markets": list(markets),
                "listing_id": listing,
            },
        )
    return removed


def apply_delivery_dates(
    engine: Engine,
    *,
    account_id: str,
    purchases: Sequence[ParsedPurchase],
) -> int:
    """Fill blank delivery dates from purchase history. Item prices stay."""

    updated = 0
    with engine.begin() as connection:
        for purchase in purchases:
            delivered = purchase.delivered_on
            if delivered is None:
                continue
            for marketplace, listing_id in _delivery_targets(
                connection,
                account_id=account_id,
                purchase=purchase,
            ):
                collector = connection.execute(
                    text(
                        """
                        UPDATE warehouse.auction_collector
                        SET manual_delivered_on = CAST(:delivered_on AS date),
                            purchase_updated_at = now()
                        WHERE account_id = CAST(:account_id AS uuid)
                          AND lower(btrim(marketplace::text)) = lower(btrim(:marketplace))
                          AND listing_id::text = CAST(:listing_id AS text)
                          AND manual_purchased IS TRUE
                          AND manual_delivered_on IS NULL
                        """
                    ),
                    {
                        "account_id": account_id,
                        "marketplace": marketplace,
                        "listing_id": listing_id,
                        "delivered_on": delivered,
                    },
                )
                updated += max(collector.rowcount or 0, 0)
                owned = connection.execute(
                    text(
                        """
                        UPDATE warehouse.owned_copy
                        SET delivered_on = CAST(:delivered_on AS date),
                            updated_at = now()
                        WHERE account_id = CAST(:account_id AS uuid)
                          AND lower(btrim(source)) = lower(btrim(:marketplace))
                          AND external_id::text = CAST(:listing_id AS text)
                          AND delivered_on IS NULL
                        """
                    ),
                    {
                        "account_id": account_id,
                        "marketplace": marketplace,
                        "listing_id": listing_id,
                        "delivered_on": delivered,
                    },
                )
                updated += max(owned.rowcount or 0, 0)
    return updated


def _delivery_targets(
    connection: Any,
    *,
    account_id: str,
    purchase: ParsedPurchase,
) -> list[tuple[str, str]]:
    """Shelf copies this history row can date: the item, or the saved order."""

    found: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(marketplace: object, listing_id: object) -> None:
        market = str(marketplace or "").strip()
        listing = str(listing_id or "").strip()
        if not market or not listing:
            return
        key = (market.lower(), listing)
        if key in seen:
            return
        seen.add(key)
        found.append((market, listing))

    item_ids = [
        value
        for value in (str(purchase.external_id or "").strip(),)
        if re.fullmatch(r"\d{9,13}", value)
    ]
    order_ids = [
        value
        for value in (
            str(purchase.order_id or "").strip(),
            str(purchase.external_id or "").strip(),
        )
        if re.fullmatch(r"\d{2}-\d{5}-\d{5}", value)
    ]
    if item_ids:
        rows = connection.execute(
            text(
                """
                SELECT marketplace::text AS marketplace, listing_id::text AS listing_id
                FROM warehouse.auction_collector
                WHERE account_id = CAST(:account_id AS uuid)
                  AND manual_purchased IS TRUE
                  AND lower(btrim(marketplace::text)) = ANY(:markets)
                  AND listing_id::text = ANY(:listing_ids)
                UNION
                SELECT source AS marketplace, external_id AS listing_id
                FROM warehouse.owned_copy
                WHERE account_id = CAST(:account_id AS uuid)
                  AND lower(btrim(source)) = ANY(:markets)
                  AND external_id::text = ANY(:listing_ids)
                """
            ),
            {
                "account_id": account_id,
                "markets": ["ebay", "gripsweat"],
                "listing_ids": item_ids,
            },
        )
        for row in rows:
            _add(row.marketplace, row.listing_id)
    if order_ids:
        rows = connection.execute(
            text(
                """
                SELECT line.marketplace AS marketplace, line.listing_id AS listing_id
                FROM warehouse.collection_bill header
                JOIN warehouse.collection_bill_line line
                  ON line.bill_id = header.id
                WHERE header.account_id = CAST(:account_id AS uuid)
                  AND header.external_order_id = ANY(:order_ids)
                UNION
                SELECT source AS marketplace, external_id AS listing_id
                FROM warehouse.owned_copy
                WHERE account_id = CAST(:account_id AS uuid)
                  AND external_id::text = ANY(:order_ids)
                """
            ),
            {"account_id": account_id, "order_ids": order_ids},
        )
        for row in rows:
            _add(row.marketplace, row.listing_id)
    return found


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


def _identity_keys(source: str, listing_id: str) -> tuple[tuple[str, str], ...]:
    listing_id = str(listing_id or "").strip()
    origin = str(source or "").strip().lower()
    if not listing_id or listing_id.lower().startswith(("detail:", "package:", "log:")):
        return ()
    if origin in _EBAY_MARKETS:
        return tuple((market, listing_id) for market in _EBAY_MARKETS)
    if origin:
        return ((origin, listing_id),)
    return ()


def _owned_identity(
    purchase: ParsedPurchase,
    owned: set[tuple[str, str]],
    purchased: set[tuple[str, str]],
) -> tuple[str, str] | None:
    for key in _identity_keys(purchase.source, purchase.external_id):
        if key in purchased or key in owned:
            return key
    return None


def _visible_listing(
    purchase: ParsedPurchase,
    listings: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    keys = _identity_keys(purchase.source, purchase.external_id)
    for key in keys:
        hit = listings.get(key)
        if hit is not None and hit.get("visible"):
            return hit
    for key in keys:
        hit = listings.get(key)
        if hit is not None:
            return hit
    return None


def _classify_one(
    purchase: ParsedPurchase,
    *,
    listings: dict[tuple[str, str], dict[str, Any]],
    owned: set[tuple[str, str]],
    purchased: set[tuple[str, str]],
    owned_catalogs: set[str],
    pressings: dict[str, tuple[PressingChoice, ...]],
    owned_rows: list[dict[str, Any]] | None = None,
    owned_pressings: dict[str, tuple[PressingChoice, ...]] | None = None,
) -> ImportMatch:
    if listing_title_is_chrome(purchase.title):
        return ImportMatch(
            purchase=purchase,
            status="left_out",
            marketplace="",
            listing_id="",
            pressings=(),
            reason="Not a listing",
        )
    if not is_collected_music(purchase.title):
        return ImportMatch(
            purchase=purchase,
            status="left_out",
            marketplace="",
            listing_id="",
            pressings=(),
            reason="Not music",
        )

    folded_catalog = fold_catalog(purchase.catalog_number)
    owned_key = _owned_identity(purchase, owned, purchased)
    if owned_key is None:
        reverse = match_record_city_bill_to_shelf(purchase, owned_rows or [])
        if reverse is not None:
            owned_key = (
                str(reverse.get("marketplace") or purchase.source),
                str(reverse.get("listing_id") or ""),
            )
            if not owned_key[1]:
                owned_key = None
    if owned_key is not None:
        owned_market, owned_listing = owned_key
        if _bill_has_charges(purchase.billing_note):
            return ImportMatch(
                purchase=purchase,
                status="backfill",
                marketplace=owned_market,
                listing_id=owned_listing,
                pressings=(),
                reason="Bill for a copy already on the shelf",
            )
        return ImportMatch(
            purchase=purchase,
            status="already",
            marketplace=owned_market,
            listing_id=owned_listing,
            pressings=(),
            reason="Already on your shelf",
        )

    listing = _visible_listing(purchase, listings)
    if listing is not None and listing["visible"]:
        return ImportMatch(
            purchase=purchase,
            status="ready",
            marketplace=str(listing["marketplace"]),
            listing_id=str(listing["listing_id"]),
            pressings=(),
            reason="",
        )
    if _fresh_marketplace_item(purchase, purchased=purchased, owned=owned):
        choices = pressings.get(folded_catalog, ()) if folded_catalog else ()
        return ImportMatch(
            purchase=purchase,
            status="new_copy",
            marketplace="",
            listing_id="",
            pressings=_single_bill_pressing(
                purchase,
                choices,
                owned_choices=(
                    (owned_pressings or {}).get(folded_catalog, ())
                    if folded_catalog
                    else ()
                ),
            ),
            reason="",
        )
    if folded_catalog and folded_catalog in owned_catalogs:
        owned_market = (
            purchase.source
            if purchase.source in {"ebay", "buyee", "discogs", "recordcity"}
            else ""
        )
        owned_listing = purchase.external_id if owned_market else ""
        if _bill_has_charges(purchase.billing_note):
            return ImportMatch(
                purchase=purchase,
                status="backfill",
                marketplace=owned_market,
                listing_id=owned_listing,
                pressings=(),
                reason="Bill for a copy already on the shelf",
            )
        return ImportMatch(
            purchase=purchase,
            status="already",
            marketplace=owned_market,
            listing_id=owned_listing,
            pressings=(),
            reason="Already on your shelf",
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
    owned_for_catalog = (
        (owned_pressings or {}).get(
            fold_catalog(purchase.catalog_number),
            (),
        )
        if fold_catalog(purchase.catalog_number)
        else ()
    )
    already_owned = _single_bill_pressing(
        purchase,
        (),
        owned_choices=owned_for_catalog,
    )
    if already_owned:
        return ImportMatch(
            purchase=purchase,
            status="new_copy",
            marketplace="",
            listing_id="",
            pressings=already_owned,
            reason="",
        )
    bill_choices = _pressings_matching_copy_media(
        purchase,
        _pressings_printed_on_bill(purchase, choices),
    )
    if len(bill_choices) > 1:
        return ImportMatch(
            purchase=purchase,
            status="pick",
            marketplace="",
            listing_id="",
            pressings=bill_choices,
            reason="More than one pressing uses this catalog",
        )
    return ImportMatch(
        purchase=purchase,
        status="new_copy",
        marketplace="",
        listing_id="",
        pressings=_single_bill_pressing(
            purchase,
            choices,
            owned_choices=(
                (owned_pressings or {}).get(
                    fold_catalog(purchase.catalog_number),
                    (),
                )
                if fold_catalog(purchase.catalog_number)
                else ()
            ),
        ),
        reason="",
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
            markets = _EBAY_MARKETS if source == "ebay" else (source,)
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
                    WHERE lower(auction.marketplace::text) = ANY(:markets)
                      AND auction.listing_id = ANY(:listing_ids)
                    """
                ),
                {
                    "account_id": account_id,
                    "markets": list(markets),
                    "listing_ids": listing_ids,
                },
            )
            for row in result.mappings():
                found[(str(row["marketplace"]), str(row["listing_id"]))] = dict(row)
    return found


def _owned_copy_rows(engine: Engine, account_id: str) -> list[dict[str, Any]]:
    """Owned shop copies, for reverse-matching a bill that lost its line id."""

    with engine.connect() as connection:
        result = connection.execute(
            text(
                """
                SELECT
                    source AS marketplace,
                    external_id AS listing_id,
                    catalog_number,
                    paid_amount AS paid,
                    paid_on
                FROM warehouse.owned_copy
                WHERE account_id = CAST(:account_id AS uuid)
                """
            ),
            {"account_id": account_id},
        )
        return [dict(row) for row in result.mappings()]


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


def _pressings_matching_copy_media(
    purchase: ParsedPurchase,
    choices: tuple[PressingChoice, ...],
) -> tuple[PressingChoice, ...]:
    """When one catalog is both an LP and an EP, the bill's format picks it."""

    if len(choices) < 2:
        return choices
    wanted = purchase_media(purchase.title, purchase.billing_note)
    if not wanted:
        return choices
    matched = tuple(
        choice for choice in choices if str(choice.media_type or "") == wanted
    )
    return matched or choices


def _pressings_printed_on_bill(
    purchase: ParsedPurchase,
    choices: tuple[PressingChoice, ...],
) -> tuple[PressingChoice, ...]:
    """Keep a pressing that is the catalog printed on the bill.

    70AH1141 and the box 70AH 1141~3 fold together. The box is a different
    copy from the single LP.
    """

    bill = purchase.catalog_number or ""
    return tuple(
        choice
        for choice in choices
        if not (
            catalog_has_range(choice.catalog_number)
            and not catalog_has_range(bill)
        )
    )


def _single_bill_pressing(
    purchase: ParsedPurchase,
    choices: tuple[PressingChoice, ...],
    owned_choices: tuple[PressingChoice, ...] = (),
) -> tuple[PressingChoice, ...]:
    owned_matched = _pressings_matching_copy_media(
        purchase,
        _pressings_printed_on_bill(purchase, owned_choices),
    )
    owned_ids = {choice.pressing_id for choice in owned_matched}
    if len(owned_ids) == 1:
        return (
            min(owned_matched, key=lambda choice: choice.pressing_id),
        )
    matched = _pressings_matching_copy_media(
        purchase,
        _pressings_printed_on_bill(purchase, choices),
    )
    if len(matched) == 1:
        return matched
    if len(choices) == 1:
        return choices
    names = {choice.catalog_number for choice in matched}
    if len(names) == 1 and matched:
        return (min(matched, key=lambda choice: choice.pressing_id),)
    names = {choice.catalog_number for choice in choices}
    if len(names) == 1 and choices:
        return (min(choices, key=lambda choice: choice.pressing_id),)
    return ()


def pressing_for_edited_catalog(
    pressing: PressingChoice | None,
    catalog: str,
) -> tuple[str, int | None]:
    """Keep the pressing when the editor catalog is the same run, spelled differently."""

    cleaned = str(catalog or "").strip()
    if pressing is None:
        return cleaned, None
    if fold_catalog(cleaned) == fold_catalog(pressing.catalog_number):
        return pressing.catalog_number, pressing.pressing_id
    return cleaned, None


def _fresh_marketplace_item(
    purchase: ParsedPurchase,
    *,
    purchased: set[tuple[str, str]],
    owned: set[tuple[str, str]],
) -> bool:
    """A different item number is another copy, even of a catalog already owned."""

    source = str(purchase.source or "").strip().lower()
    external = str(purchase.external_id or "").strip()
    if source not in {"ebay", "buyee", "gripsweat", "discogs", "recordcity"}:
        return False
    # eBay and Record City ids are digits. A Buyee auction is a letter plus digits.
    if not external.isdigit() and _BUYEE_ITEM_ID.fullmatch(external) is None:
        return False
    markets = {"ebay", "gripsweat"} if source in {"ebay", "gripsweat"} else {source}
    held = purchased | owned
    return not any((market, external) in held for market in markets)


def _owned_pressings_by_catalog(
    engine: Engine,
    account_id: str,
) -> dict[str, tuple[PressingChoice, ...]]:
    """Pressings this account already attached to a catalog."""

    with engine.connect() as connection:
        rows = list(
            connection.execute(
                text(
                    """
                    SELECT
                        pressing.id AS pressing_id,
                        pressing.catalog_number,
                        COALESCE(family.display_artist, '') AS artist_name,
                        COALESCE(family.display_title, '') AS album_title,
                        COALESCE(pressing.media_type, '') AS media_type
                    FROM warehouse.owned_copy owned
                    JOIN warehouse.pressing_identity pressing
                      ON pressing.id = owned.pressing_id
                    LEFT JOIN warehouse.release_family family
                      ON family.id = pressing.release_family_id
                    WHERE owned.account_id = CAST(:account_id AS uuid)
                      AND owned.pressing_id IS NOT NULL
                    UNION
                    SELECT
                        pressing.id AS pressing_id,
                        pressing.catalog_number,
                        COALESCE(family.display_artist, '') AS artist_name,
                        COALESCE(family.display_title, '') AS album_title,
                        COALESCE(pressing.media_type, '') AS media_type
                    FROM warehouse.auction_collector owned
                    JOIN warehouse.auction_pressing_assignment assigned
                      ON assigned.marketplace::text =
                         owned.marketplace::text
                     AND assigned.listing_id::text =
                         owned.listing_id::text
                    JOIN warehouse.pressing_identity pressing
                      ON pressing.id = assigned.pressing_id
                    LEFT JOIN warehouse.release_family family
                      ON family.id = pressing.release_family_id
                    WHERE owned.account_id = CAST(:account_id AS uuid)
                      AND owned.manual_purchased IS TRUE
                    """
                ),
                {"account_id": account_id},
            ).mappings()
        )
    grouped: dict[str, dict[int, PressingChoice]] = {}
    for row in rows:
        catalog = str(row["catalog_number"] or "")
        folded = fold_catalog(catalog)
        if not folded:
            continue
        choice = PressingChoice(
            pressing_id=int(row["pressing_id"]),
            catalog_number=catalog,
            artist_name=str(row["artist_name"] or ""),
            album_title=str(row["album_title"] or ""),
            media_type=str(row["media_type"] or ""),
        )
        grouped.setdefault(folded, {})[choice.pressing_id] = choice
    return {key: tuple(value.values()) for key, value in grouped.items()}


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
                    COALESCE(family.display_title, '') AS album_title,
                    COALESCE(pressing.media_type, '') AS media_type
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
                    media_type=str(row["media_type"] or ""),
                )
            )
    return {key: tuple(value) for key, value in grouped.items()}
