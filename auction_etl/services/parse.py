from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select

from auction_etl.models.raw import RawPage
from auction_etl.models.staging import Listing
from auction_etl.parsers.buyee import parse_search as parse_buyee
from auction_etl.parsers.ebay import parse_search as parse_ebay
from auction_etl.services.dates import parse_ended_at


_INT_RE = re.compile(r"([0-9][0-9,]*)")
_SOLD_AMOUNT = (
    r"([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)"
)
_SOLD_MONEY_PATTERNS = (
    (re.compile(rf"\bAU\s*\$\s*{_SOLD_AMOUNT}", re.IGNORECASE), "AUD"),
    (re.compile(rf"\bC(?:A)?\s*\$\s*{_SOLD_AMOUNT}", re.IGNORECASE), "CAD"),
    (re.compile(rf"\bUS\s*\$\s*{_SOLD_AMOUNT}", re.IGNORECASE), "USD"),
    (re.compile(rf"\bUSD\s*{_SOLD_AMOUNT}", re.IGNORECASE), "USD"),
    (re.compile(rf"\bGBP\s*{_SOLD_AMOUNT}", re.IGNORECASE), "GBP"),
    (re.compile(rf"£\s*{_SOLD_AMOUNT}"), "GBP"),
    (re.compile(rf"\bEUR\s*{_SOLD_AMOUNT}", re.IGNORECASE), "EUR"),
    (re.compile(rf"€\s*{_SOLD_AMOUNT}"), "EUR"),
    (re.compile(rf"\bJPY\s*{_SOLD_AMOUNT}", re.IGNORECASE), "JPY"),
    (re.compile(rf"¥\s*{_SOLD_AMOUNT}"), "JPY"),
    (re.compile(rf"\$\s*{_SOLD_AMOUNT}"), None),
)


def parse_sold_money(value: object) -> tuple[Decimal | None, str | None]:
    """Parse a sold-card amount and its currency.

    Bare ``$`` is a display amount, not official USD. Explicit ``US $`` / ``USD``,
    ``GBP`` / ``£``, ``EUR`` / ``€``, ``AU $``, and ``C $`` are local currencies.
    """

    if value is None or value == "":
        return None, None

    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value)), None

    text = str(value)
    for pattern, currency in _SOLD_MONEY_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        return Decimal(match.group(1).replace(",", "")), currency

    return None, None


def _listing_image_url(listing: dict) -> str | None:
    """Accept both Buyee `image` and eBay `image_url` parser keys."""
    for key in ("image", "image_url"):
        value = listing.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _parse_money(value):
    return parse_sold_money(value)


def sold_card_hammer(
    sale_type: object,
    price: object,
) -> tuple[Decimal | None, str | None]:
    """Hammer from a sold-search card.

    Best Offer cards still print the ask. That is not the accepted offer.
    """
    amount, currency = parse_sold_money(price)
    if str(sale_type or "") == "FIXED_PRICE_OBO":
        return None, currency
    return amount, currency


EBAY_US_TAX_RATE = Decimal("0.0625")


def apply_ebay_us_tax(
    hammer: Decimal | None,
    *,
    currency: str | None,
) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
    """US eBay sales tax sits on the hammer. Missing hammers stay empty."""
    if hammer is None:
        return None, None, None, None
    if str(currency or "").upper() != "USD":
        return hammer, None, hammer, None
    tax = (hammer * EBAY_US_TAX_RATE).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    return hammer, tax, hammer + tax, EBAY_US_TAX_RATE


@dataclass(slots=True)
class ParseStats:
    pages: int = 0
    listings: int = 0


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

        final_price, currency = sold_card_hammer(
            listing.get("sale_type"),
            listing.get("price"),
        )
        shipping_price, shipping_currency = _parse_money(
            listing.get("shipping")
        )
        payload = listing.get("payload", listing)
        if not isinstance(payload, dict):
            payload = {"value": payload}
        else:
            payload = dict(payload)
        asking = listing.get("start_price")
        if asking:
            payload["start_price"] = asking

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
                image_url=_listing_image_url(listing),
                condition_text=listing.get("condition"),
                payload=payload,
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
