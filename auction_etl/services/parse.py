from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from auction_etl.models.raw import RawPage
from auction_etl.models.warehouse import Auction
from auction_etl.classifiers import classify_media
from auction_etl.parsers.ebay import parse_search

_PRICE_RE = re.compile(r"([0-9][0-9,]*\.?[0-9]*)")
_INT_RE = re.compile(r"(\d+)")


def _parse_money(value: str | None) -> tuple[Decimal | None, str | None]:
    if not value:
        return None, None

    currency = None

    if "$" in value:
        currency = "USD"
    elif "£" in value:
        currency = "GBP"
    elif "€" in value:
        currency = "EUR"

    match = _PRICE_RE.search(value)

    if not match:
        return None, currency

    return Decimal(match.group(1).replace(",", "")), currency


def _parse_int(value: str | None) -> int | None:
    if not value:
        return None

    match = _INT_RE.search(value)

    if not match:
        return None

    return int(match.group(1))


def parse_raw_page(
    session: Session,
    raw: RawPage,
) -> int:
    listings = parse_search(raw.html)

    imported = 0

    for listing in listings:

        auction = session.scalar(
            select(Auction).where(
                Auction.marketplace == "ebay",
                Auction.listing_id == listing["item_id"],
            )
        )

        if auction is None:
            auction = Auction(
                marketplace="ebay",
                listing_id=listing["item_id"],
            )
            session.add(auction)

        final_price, currency = _parse_money(
            listing.get("price")
        )

        shipping_price, shipping_currency = _parse_money(
            listing.get("shipping")
        )

        auction.auction_url = listing["url"]
        auction.title = listing.get("title") or ""
        auction.seller = listing.get("seller")

        auction.final_price = final_price
        auction.shipping_price = shipping_price

        auction.currency = (
            currency
            or shipping_currency
            or auction.currency
        )

        auction.bid_count = _parse_int(
            listing.get("bids")
        )

        condition = listing.get("condition")

        if condition:
            auction.condition_media = condition
            auction.condition_cover = condition

        auction.media_type = classify_media(
            auction.title
        )

        title = auction.title.lower()

        auction.bulk_lot = (
            auction.media_type is None
            and any(
                word in title
                for word in (
                    "lot",
                    "bundle",
                    "collection",
                    "bulk",
                )
            )
        )

        imported += 1

    session.flush()

    return imported


def parse_latest(
    session: Session,
) -> tuple[RawPage, int]:
    raw = session.scalar(
        select(RawPage)
        .order_by(RawPage.id.desc())
    )

    if raw is None:
        raise RuntimeError("No raw pages found.")

    imported = parse_raw_page(
        session=session,
        raw=raw,
    )

    session.commit()

    return raw, imported


def parse_page_id(
    session: Session,
    page_id: int,
) -> tuple[RawPage, int]:
    raw = session.get(
        RawPage,
        page_id,
    )

    if raw is None:
        raise RuntimeError(
            f"Raw page {page_id} not found."
        )

    imported = parse_raw_page(
        session=session,
        raw=raw,
    )

    session.commit()

    return raw, imported


def sync_pages(
    session: Session,
) -> tuple[int, int]:
    pages = session.scalars(
        select(RawPage)
        .where(RawPage.parsed_at.is_(None))
        .order_by(RawPage.id)
    ).all()

    page_count = 0
    listing_count = 0

    for raw in pages:
        imported = parse_raw_page(
            session=session,
            raw=raw,
        )

        raw.listing_count = imported
        raw.parsed_at = func.now()

        page_count += 1
        listing_count += imported

        print(
            f"Page {raw.id}: {imported} listings"
        )

    session.commit()

    return page_count, listing_count
