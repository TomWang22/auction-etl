from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from auction_etl.models.staging import Listing
from auction_etl.classifiers import classify_media_details
from auction_etl.models.warehouse import Auction


_BULK_RE = re.compile(
    r"\b(?:lot|bundle|collection|set|box\s*set|まとめ|セット)\b",
    re.IGNORECASE,
)

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


def _is_bulk_lot(
    listing: Listing,
) -> bool:
    text = " ".join(
        value
        for value in (
            listing.title,
            listing.subtitle,
            listing.description,
        )
        if value
    )

    return bool(
        _BULK_RE.search(text)
    )


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
    gross = _decimal_or_none(
        listing.final_price
    )

    if listing.marketplace != "buyee":
        return (
            gross,
            None,
            gross,
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
            _clean(listing.format)
            or media.format
        ),
        "disc_count": (
            listing.disc_count
            or media.disc_count
        ),
        "edition": _clean(listing.edition),
        "catalog_number": _clean(
            listing.catalog_number
        ),
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
        "start_price": None,
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
    }


def _prune_obsolete(
    session: Session,
    marketplace: str | None,
) -> int:
    staging_statement = select(
        Listing.marketplace,
        Listing.listing_id,
    )

    warehouse_statement = select(Auction)

    if marketplace:
        staging_statement = (
            staging_statement.where(
                Listing.marketplace
                == marketplace
            )
        )
        warehouse_statement = (
            warehouse_statement.where(
                Auction.marketplace
                == marketplace
            )
        )

    staging_keys = set(
        session.execute(
            staging_statement
        ).all()
    )

    pruned = 0

    for auction in session.scalars(
        warehouse_statement
    ):
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
    prune: bool = True,
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

        update_values = {
            key: value
            for key, value in values.items()
            if key not in {
                "marketplace",
                "listing_id",
            }
        }

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

    if prune:
        stats.pruned = _prune_obsolete(
            session,
            marketplace,
        )

    session.commit()
    return stats


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
