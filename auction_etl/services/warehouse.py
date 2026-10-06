from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from auction_etl.models.staging import Listing
from auction_etl.classifiers import (
    classify_condition,
    classify_media_details,
    extract_record_label,
    is_canonical_grade,
    is_job_lot,
)
from auction_etl.models.warehouse import Auction
from auction_etl.services.discogs_identity import catalog_token, is_junk_catalog
from auction_etl.services.parse import apply_ebay_us_tax, parse_sold_money

_TAX_AMOUNT_RE = re.compile(
    r"(?:Tax|税)\s*[:：]?\s*"
    r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*"
    r"(?:yen|円)",
    re.IGNORECASE,
)

_TAX_PERCENT_RE = re.compile(
    r"(?:Tax|税)\s*[:：]?\s*"
    r"([0-9]+(?:\.[0-9]+)?)\s*%",
    re.IGNORECASE,
)

_ARTIST_SEPARATORS = (
    " - ",
    " / ",
    " – ",
    " — ",
    " | ",
)



@dataclass(slots=True)
class WarehouseStats:
    scanned: int = 0
    inserted_or_updated: int = 0
    pruned: int = 0


def _clean(value: str | None) -> str | None:
    if value is None:
        return None

    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip()

    return value or None


def _extract_artist(
    title: str | None,
) -> str | None:
    title = _clean(title)

    if not title:
        return None

    lowered = title.casefold()

    known = (
        ("teresa teng", "Teresa Teng"),
        ("テレサ・テン", "Teresa Teng"),
        ("テレサ テン", "Teresa Teng"),
        ("鄧麗君", "Teresa Teng"),
        ("邓丽君", "Teresa Teng"),
    )

    for needle, artist in known:
        if needle in lowered:
            return artist

    for separator in _ARTIST_SEPARATORS:
        if separator not in title:
            continue

        first, remainder = title.split(
            separator,
            1,
        )

        first = _clean(first)
        remainder = _clean(remainder)

        if (
            first
            and remainder
            and len(first) <= 100
        ):
            return first

    return None


def _listing_classify_text(
    listing: Listing,
) -> str:
    return " ".join(
        value
        for value in (
            listing.title,
            listing.subtitle,
            listing.description,
        )
        if value
    )


def _is_bulk_lot(
    listing: Listing,
) -> bool:
    text = _listing_classify_text(listing)
    return classify_media_details(text).bulk_lot or is_job_lot(text)


def _currency(
    listing: Listing,
) -> str:
    if listing.currency:
        return listing.currency.upper()

    if listing.marketplace == "buyee":
        return "JPY"

    if listing.marketplace == "ebay":
        return "USD"

    return "USD"


def _decimal_or_none(
    value,
) -> Decimal | None:
    if value is None:
        return None

    return Decimal(str(value))


def _price_components(
    listing: Listing,
) -> tuple[
    Decimal | None,
    Decimal | None,
    Decimal | None,
    Decimal | None,
    bool | None,
]:
    hammer = _decimal_or_none(
        listing.final_price
    )

    if listing.marketplace == "ebay":
        hammer, tax, gross, tax_rate = apply_ebay_us_tax(
            hammer,
            currency=_currency(listing),
        )
        return (
            hammer,
            tax,
            gross,
            tax_rate,
            False if tax is not None else None,
        )

    if listing.marketplace != "buyee":
        return (
            hammer,
            None,
            hammer,
            None,
            None,
        )

    payload = listing.payload or {}
    details = payload.get(
        "price_details"
    ) or {}

    hammer = _decimal_or_none(
        details.get("hammer_price_jpy")
    )
    tax = _decimal_or_none(
        details.get("tax_amount_jpy")
    )
    parsed_gross = _decimal_or_none(
        details.get("gross_price_jpy")
    )
    tax_rate = _decimal_or_none(
        details.get("tax_rate")
    )
    includes_tax = details.get(
        "price_includes_tax"
    )

    gross = parsed_gross or gross

    if hammer is None and gross is not None:
        hammer = gross

    if (
        gross is None
        and hammer is not None
    ):
        gross = hammer + (
            tax or Decimal("0")
        )

    return (
        hammer,
        tax,
        gross,
        tax_rate,
        includes_tax,
    )


def _sale_format(value: str | None) -> str | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    return (
        cleaned
        .upper()
        .replace(" ", "_")
        .replace("-", "_")
    )


def _start_price(listing: Listing) -> Decimal | None:
    payload = listing.payload if isinstance(listing.payload, dict) else {}
    nested = payload.get("price_details")
    if not isinstance(nested, dict):
        nested = {}
    for raw in (
        nested.get("starting_price"),
        nested.get("start_price"),
        payload.get("starting_price"),
        payload.get("start_price"),
    ):
        if raw is None or raw == "":
            continue
        amount, _currency = parse_sold_money(raw)
        if amount is not None:
            return amount
        try:
            return Decimal(str(raw).replace(",", ""))
        except (InvalidOperation, ValueError):
            continue
    return None


def _conflict_updates(values: dict) -> dict:
    """Keep detail-enriched seller, start price, and sale format on refresh."""
    updates = {
        key: value
        for key, value in values.items()
        if key not in {
            "marketplace",
            "listing_id",
            "seller",
            "start_price",
            "auction_format",
            "watch_count",
            "label",
            "condition_media",
            "condition_cover",
        }
    }
    updates["seller"] = text(
        """
        CASE
          WHEN warehouse.auction.seller IS NOT NULL
           AND BTRIM(warehouse.auction.seller) <> ''
           AND EXCLUDED.seller ~ '^[A-Za-z0-9]{16,}$'
           AND warehouse.auction.seller !~ '^[A-Za-z0-9]{16,}$'
          THEN warehouse.auction.seller
          ELSE COALESCE(
            NULLIF(BTRIM(EXCLUDED.seller), ''),
            warehouse.auction.seller
          )
        END
        """
    )
    updates["start_price"] = text(
        "COALESCE(EXCLUDED.start_price, warehouse.auction.start_price)"
    )
    updates["final_price"] = text(
        """
        CASE
          WHEN EXCLUDED.auction_format = 'FIXED_PRICE_OBO'
           AND EXCLUDED.final_price IS NULL
           AND warehouse.auction.final_price
               IS NOT DISTINCT FROM warehouse.auction.start_price
          THEN NULL
          ELSE COALESCE(
            EXCLUDED.final_price,
            warehouse.auction.final_price
          )
        END
        """
    )
    updates["gross_price"] = text(
        """
        CASE
          WHEN EXCLUDED.auction_format = 'FIXED_PRICE_OBO'
           AND EXCLUDED.gross_price IS NULL
           AND warehouse.auction.gross_price
               IS NOT DISTINCT FROM warehouse.auction.start_price
          THEN NULL
          ELSE COALESCE(
            EXCLUDED.gross_price,
            warehouse.auction.gross_price
          )
        END
        """
    )
    updates["tax_amount"] = text(
        "COALESCE(EXCLUDED.tax_amount, warehouse.auction.tax_amount)"
    )
    updates["tax_rate"] = text(
        "COALESCE(EXCLUDED.tax_rate, warehouse.auction.tax_rate)"
    )
    updates["auction_format"] = text(
        """
        COALESCE(
            NULLIF(BTRIM(EXCLUDED.auction_format), ''),
            warehouse.auction.auction_format
        )
        """
    )
    updates["label"] = text(
        """
        COALESCE(
            NULLIF(BTRIM(EXCLUDED.label), ''),
            warehouse.auction.label
        )
        """
    )
    updates["condition_media"] = text(
        """
        COALESCE(
            NULLIF(BTRIM(EXCLUDED.condition_media), ''),
            warehouse.auction.condition_media
        )
        """
    )
    updates["condition_cover"] = text(
        """
        COALESCE(
            NULLIF(BTRIM(EXCLUDED.condition_cover), ''),
            warehouse.auction.condition_cover
        )
        """
    )
    return updates


def promote_sale_facts(
    session: Session,
    *,
    marketplace: str | None = None,
) -> None:
    """Restore seller, opened, start price, and sale type after a card sync."""
    scoped = ""
    params: dict[str, str] = {}
    if marketplace:
        scoped = " AND auction.marketplace = :marketplace"
        params["marketplace"] = marketplace
    session.execute(
        text(
            f"""
            UPDATE warehouse.auction AS auction
            SET
                seller = CASE
                  WHEN BTRIM(COALESCE(detail.seller_name, '')) <> ''
                   AND (
                     auction.seller IS NULL
                     OR BTRIM(auction.seller) = ''
                     OR auction.seller ~ '^[A-Za-z0-9]{{16,}}$'
                   )
                  THEN BTRIM(detail.seller_name)
                  ELSE auction.seller
                END,
                opening_at = COALESCE(auction.opening_at, detail.opening_at),
                closing_at = COALESCE(auction.closing_at, detail.closing_at),
                start_price = COALESCE(auction.start_price, detail.starting_price),
                buyout_price_gross = COALESCE(
                    auction.buyout_price_gross,
                    detail.buyout_price_gross
                )
            FROM warehouse.auction_detail AS detail
            WHERE detail.marketplace = auction.marketplace
              AND detail.listing_id = auction.listing_id
              {scoped}
            """
        ),
        params,
    )
    session.execute(
        text(
            f"""
            UPDATE warehouse.auction AS auction
            SET auction_format = UPPER(REPLACE(REPLACE(BTRIM(listing.sale_type), ' ', '_'), '-', '_'))
            FROM staging.listing AS listing
            WHERE listing.marketplace = auction.marketplace
              AND listing.listing_id = auction.listing_id
              AND listing.sale_type IS NOT NULL
              AND BTRIM(listing.sale_type) <> ''
              AND (
                auction.auction_format IS NULL
                OR BTRIM(auction.auction_format) = ''
                OR auction.auction_format = 'UNKNOWN'
              )
              {scoped}
            """
        ),
        params,
    )
    session.execute(
        text(
            f"""
            UPDATE warehouse.auction AS auction
            SET auction_format = CASE
                WHEN buyout_price_gross IS NOT NULL
                 AND COALESCE(bid_count, 0) > 0
                    THEN 'AUCTION_WITH_BUYOUT'
                WHEN buyout_price_gross IS NOT NULL
                 AND COALESCE(bid_count, 0) = 0
                    THEN 'FIXED_PRICE'
                WHEN COALESCE(bid_count, 0) > 0
                  OR start_price IS NOT NULL
                    THEN 'AUCTION'
                WHEN marketplace = 'ebay'
                 AND ended_at IS NOT NULL
                    THEN 'FIXED_PRICE'
                WHEN marketplace = 'buyee'
                    THEN 'AUCTION'
                ELSE 'UNKNOWN'
            END
            WHERE (
                auction.auction_format IS NULL
                OR BTRIM(auction.auction_format) = ''
                OR auction.auction_format = 'UNKNOWN'
            )
            {scoped}
            """
        ),
        params,
    )
    promote_classification_facts(session, marketplace=marketplace)


def promote_classification_facts(
    session: Session,
    *,
    marketplace: str | None = None,
) -> None:
    """Fill labels, catalogs, and grades from staging, details, and Discogs."""
    scoped = ""
    params: dict[str, str] = {}
    if marketplace:
        scoped = " AND auction.marketplace = :marketplace"
        params["marketplace"] = marketplace
    session.execute(
        text(
            f"""
            UPDATE warehouse.auction AS auction
            SET
                label = COALESCE(
                    NULLIF(BTRIM(auction.label), ''),
                    NULLIF(BTRIM(listing.label), '')
                ),
                catalog_number = COALESCE(
                    NULLIF(BTRIM(auction.catalog_number), ''),
                    NULLIF(BTRIM(listing.catalog_number), '')
                ),
                media_type = COALESCE(
                    NULLIF(BTRIM(auction.media_type), ''),
                    NULLIF(BTRIM(listing.format), '')
                )
            FROM staging.listing AS listing
            WHERE listing.marketplace = auction.marketplace
              AND listing.listing_id = auction.listing_id
              {scoped}
            """
        ),
        params,
    )
    session.execute(
        text(
            f"""
            UPDATE warehouse.auction AS auction
            SET
                label = COALESCE(
                    NULLIF(BTRIM(auction.label), ''),
                    NULLIF(BTRIM(canonical.display_name), ''),
                    NULLIF(BTRIM(pressing.label_name), '')
                ),
                catalog_number = COALESCE(
                    NULLIF(BTRIM(auction.catalog_number), ''),
                    NULLIF(BTRIM(pressing.catalog_number), '')
                )
            FROM warehouse.auction_pressing_assignment AS assignment
            JOIN warehouse.pressing_identity AS pressing
              ON pressing.id = assignment.pressing_id
            LEFT JOIN warehouse.label AS canonical
              ON canonical.id = pressing.label_id
            WHERE assignment.marketplace = auction.marketplace
              AND assignment.listing_id = auction.listing_id
              AND auction.identity_status IN ('filled_auto', 'filled_manual')
              {scoped}
            """
        ),
        params,
    )
    rows = session.execute(
        text(
            f"""
            SELECT
                auction.marketplace,
                auction.listing_id,
                auction.title,
                auction.artist,
                auction.label,
                auction.catalog_number,
                auction.condition_media,
                auction.condition_cover,
                auction.bulk_lot,
                detail.condition_text,
                detail.description
            FROM warehouse.auction AS auction
            LEFT JOIN warehouse.auction_detail AS detail
              ON detail.marketplace = auction.marketplace
             AND detail.listing_id = auction.listing_id
            WHERE TRUE
              {scoped}
            """
        ),
        params,
    ).mappings().all()
    for row in rows:
        title = str(row.get("title") or "")
        catalog = str(row.get("catalog_number") or "").strip() or None
        if catalog and is_junk_catalog(catalog, title=title):
            catalog = None
        if not catalog:
            catalog = catalog_token(title=title)
        label = str(row.get("label") or "").strip() or None
        if not label:
            label = extract_record_label(
                " ".join(
                    part
                    for part in (row.get("artist"), title)
                    if part
                )
            )
        current_media = str(row.get("condition_media") or "").strip() or None
        current_cover = str(row.get("condition_cover") or "").strip() or None
        grades = classify_condition(
            row.get("description"),
            row.get("condition_text"),
            title,
        )
        media_grade = (
            current_media
            if is_canonical_grade(current_media)
            else grades.media_grade
        )
        cover_grade = (
            current_cover
            if is_canonical_grade(current_cover)
            else grades.cover_grade
        )
        media = classify_media_details(title)
        job = is_job_lot(title)
        if job and catalog and is_junk_catalog(catalog, title=title):
            catalog = None
        session.execute(
            text(
                """
                UPDATE warehouse.auction
                SET
                    catalog_number = CAST(:catalog_number AS varchar),
                    bulk_lot = CAST(:bulk_lot AS boolean),
                    label = COALESCE(
                        NULLIF(BTRIM(label), ''),
                        CAST(:label AS varchar)
                    ),
                    condition_media = COALESCE(
                        CAST(:media_grade AS varchar),
                        condition_media
                    ),
                    condition_cover = COALESCE(
                        CAST(:cover_grade AS varchar),
                        condition_cover
                    )
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "catalog_number": catalog,
                "bulk_lot": bool(media.bulk_lot or job),
                "label": label,
                "media_grade": media_grade,
                "cover_grade": cover_grade,
                "marketplace": row["marketplace"],
                "listing_id": row["listing_id"],
            },
        )


def _row_values(
    listing: Listing,
) -> dict:
    title = (
        _clean(listing.title)
        or listing.listing_id
    )

    (
        hammer_price,
        tax_amount,
        gross_price,
        tax_rate,
        price_includes_tax,
    ) = _price_components(listing)

    media = classify_media_details(
        listing.title
    )

    return {
        "marketplace": listing.marketplace,
        "listing_id": listing.listing_id,
        "auction_url": listing.auction_url,
        "seller": _clean(listing.seller),
        "artist": _extract_artist(title),
        "title": title,
        "media_type": (
            media.format
            or _clean(listing.format)
        ),
        "disc_count": (
            listing.disc_count
            or media.disc_count
        ),
        "edition": _clean(listing.edition),
        "catalog_number": catalog_token(
            catalog_number=listing.catalog_number,
            title=title,
        ),
        "label": _clean(listing.label),
        "image_url": _clean(listing.image_url),
        "condition_media": _clean(
            listing.media_condition
        ),
        "condition_cover": _clean(
            listing.sleeve_condition
        ),
        "bulk_lot": (
            _is_bulk_lot(listing)
            or media.bulk_lot
        ),
        "bid_count": listing.bid_count,
        "watch_count": None,
        "start_price": _start_price(listing),
        "final_price": hammer_price,
        "tax_amount": tax_amount,
        "gross_price": gross_price,
        "tax_rate": tax_rate,
        "price_includes_tax": price_includes_tax,
        "shipping_price": (
            listing.shipping_price
        ),
        "currency": _currency(listing),
        "ended_at": listing.ended_at,
        "auction_format": _sale_format(listing.sale_type),
    }


def _prune_obsolete(
    session: Session,
    marketplace: str | None,
) -> int:
    """Prune only a complete, explicitly scoped marketplace snapshot."""
    if marketplace is None:
        raise RuntimeError(
            "Global warehouse pruning is disabled. "
            "Specify one marketplace explicitly."
        )

    staging_statement = select(
        Listing.marketplace,
        Listing.listing_id,
    ).where(
        Listing.marketplace == marketplace
    )

    warehouse_statement = select(
        Auction
    ).where(
        Auction.marketplace == marketplace
    )

    staging_keys = set(
        session.execute(
            staging_statement
        ).all()
    )

    warehouse_rows = list(
        session.scalars(
            warehouse_statement
        )
    )

    if warehouse_rows and not staging_keys:
        raise RuntimeError(
            "Refusing to prune because staging contains no "
            f"{marketplace} rows."
        )

    if len(staging_keys) < len(warehouse_rows):
        raise RuntimeError(
            "Refusing to prune an incomplete marketplace snapshot: "
            f"staging has {len(staging_keys)} unique keys while "
            f"warehouse has {len(warehouse_rows)} {marketplace} rows."
        )

    pruned = 0

    for auction in warehouse_rows:
        key = (
            auction.marketplace,
            auction.listing_id,
        )

        if key in staging_keys:
            continue

        session.delete(auction)
        pruned += 1

    return pruned


def sync_staging_to_warehouse(
    session: Session,
    *,
    marketplace: str | None = None,
    prune: bool = False,
) -> WarehouseStats:
    statement = select(Listing).order_by(
        Listing.id
    )

    if marketplace:
        statement = statement.where(
            Listing.marketplace
            == marketplace
        )

    stats = WarehouseStats()

    for listing in session.scalars(
        statement
    ):
        stats.scanned += 1
        values = _row_values(listing)

        insert_statement = insert(
            Auction
        ).values(**values)

        update_values = _conflict_updates(values)

        upsert_statement = (
            insert_statement
            .on_conflict_do_update(
                constraint=(
                    "uq_auction_marketplace_listing"
                ),
                set_=update_values,
            )
        )

        session.execute(
            upsert_statement
        )

        stats.inserted_or_updated += 1

    promote_sale_facts(session, marketplace=marketplace)

    if prune:
        stats.pruned = _prune_obsolete(
            session,
            marketplace,
        )

    session.commit()
    return stats


def new_warehouse_identities(
    existing_listing_ids: Iterable[str],
    parsed_listing_ids: Iterable[str],
) -> frozenset[str]:
    """Return listing IDs that would insert new warehouse identities.

    Warehouse sync upserts on uq_auction_marketplace_listing. Existing
    (marketplace, listing_id) keys do not inflate warehouse identity
    counts. --no-prune keeps unmatched warehouse rows.
    """

    existing = {
        str(value).strip()
        for value in existing_listing_ids
        if str(value).strip()
    }
    parsed = {
        str(value).strip()
        for value in parsed_listing_ids
        if str(value).strip()
    }
    return frozenset(parsed - existing)


def warehouse_counts(
    session: Session,
) -> list[tuple[str, int]]:
    return list(
        session.execute(
            select(
                Auction.marketplace,
                func.count(Auction.id),
            )
            .group_by(
                Auction.marketplace
            )
            .order_by(
                Auction.marketplace
            )
        ).all()
    )
