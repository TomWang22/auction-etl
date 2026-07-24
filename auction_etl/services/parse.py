from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from auction_etl.models.raw import RawPage
from auction_etl.models.staging import Listing
from auction_etl.parsers.buyee import parse_search as parse_buyee
from auction_etl.parsers.ebay import parse_search as parse_ebay
from auction_etl.services.dates import parse_ended_at


_MONEY_RE = re.compile(r"([A-Z]{3}|[$£€¥])?\s*([0-9][0-9,]*(?:\.[0-9]{2})?)")
_INT_RE = re.compile(r"([0-9][0-9,]*)")


@dataclass(slots=True)
class ParseStats:
    pages: int = 0
    listings: int = 0


def _parse_money(value):
    if value is None:
        return None, None

    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value)), None

    match = _MONEY_RE.search(str(value))
    if match is None:
        return None, None

    currency = {
        "$": "USD",
        "£": "GBP",
        "€": "EUR",
        "¥": "JPY",
    }.get(match.group(1), match.group(1))

    return Decimal(match.group(2).replace(",", "")), currency


def _parse_int(value):
    if value is None:
        return None

    if isinstance(value, int):
        return value

    match = _INT_RE.search(str(value))
    if match is None:
        return None

    return int(match.group(1).replace(",", ""))


def _parser(source: str):
    parser = {
        "ebay": parse_ebay,
        "buyee": parse_buyee,
    }.get(source)

    if parser is None:
        raise ValueError(f"Unsupported source: {source}")

    return parser


def parse_raw_page(session, raw: RawPage) -> int:
    listings = _parser(raw.source)(raw.html)

    session.query(Listing).filter(
        Listing.raw_page_id == raw.id
    ).delete(synchronize_session=False)

    for listing in listings:
        listing_id = str(listing["item_id"])

        session.query(Listing).filter(
            Listing.marketplace == raw.source,
            Listing.listing_id == listing_id,
        ).delete(synchronize_session=False)

        final_price, currency = _parse_money(listing.get("price"))
        shipping_price, shipping_currency = _parse_money(
            listing.get("shipping")
        )

        session.add(
            Listing(
                raw_page_id=raw.id,
                marketplace=raw.source,
                listing_id=listing_id,
                auction_url=listing["url"],
                title=listing.get("title"),
                subtitle=listing.get("subtitle"),
                description=listing.get("description"),
                sold_text=listing.get("ended"),
                ended_at=parse_ended_at(
                    listing.get("ended"),
                    raw.source,
                ),
                sale_type=listing.get("sale_type"),
                price_text=listing.get("price"),
                final_price=final_price,
                currency=currency or shipping_currency,
                bid_text=listing.get("bids"),
                bid_count=_parse_int(listing.get("bids")),
                shipping_text=listing.get("shipping"),
                shipping_price=shipping_price,
                location=listing.get("location"),
                seller=listing.get("seller"),
                seller_feedback=listing.get("feedback"),
                image_url=listing.get("image"),
                condition_text=listing.get("condition"),
                payload=listing.get("payload", listing),
            )
        )

    raw.listing_count = len(listings)
    raw.parsed_at = datetime.now(timezone.utc)

    session.flush()

    return len(listings)


def parse_pages(session, pages) -> ParseStats:
    stats = ParseStats()

    for page in pages:
        stats.pages += 1
        stats.listings += parse_raw_page(session, page)

    session.commit()
    return stats


def parse_latest(session, force: bool = False) -> ParseStats:
    stmt = select(RawPage).order_by(RawPage.id)

    if not force:
        stmt = stmt.where(RawPage.parsed_at.is_(None))

    return parse_pages(session, session.scalars(stmt))


def parse_all(session, force: bool = False) -> ParseStats:
    return parse_latest(session, force=force)


def parse_source(session, source: str, force: bool = False) -> ParseStats:
    stmt = (
        select(RawPage)
        .where(RawPage.source == source)
        .order_by(RawPage.id)
    )

    if not force:
        stmt = stmt.where(RawPage.parsed_at.is_(None))

    return parse_pages(session, session.scalars(stmt))


def parse_page(session, page_id: int) -> ParseStats:
    page = session.get(RawPage, page_id)

    if page is None:
        raise ValueError(f"RawPage {page_id} not found")

    return parse_pages(session, [page])


def sync_pages(session):
    return parse_latest(session)
