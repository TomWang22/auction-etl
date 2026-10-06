"""Flag eBay completed/sold listing URLs that also appear on Gripsweat."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse

from auction_etl.reporting.main_review_integration import (
    gripsweat_original_listing_id,
)
from sqlalchemy import text
from sqlalchemy.engine import Engine

from auction_etl.services.parse import apply_ebay_us_tax, parse_sold_money


EBAY_ITM_PATTERN = re.compile(
    r"/itm/(?:[^/?#]+/)?(?P<item_id>[0-9]{9,15})(?:[/?#]|$)",
    re.IGNORECASE,
)

SOLD_CARD_DATE_PATTERN = re.compile(
    r"Sold\s+(?P<date>[A-Za-z]{3,9}\s+[0-9]{1,2},\s+[0-9]{4})",
    re.IGNORECASE,
)
_ASK_HAMMER_DELTA = Decimal("1.00")
_ASK_HAMMER_RATIO = Decimal("0.02")


@dataclass(frozen=True, slots=True)
class SoldItem:
    """One completed/sold eBay card or warehouse sold URL."""

    listing_id: str
    url: str
    title: str = ""
    price_text: str = ""
    ended_text: str = ""
    price: Decimal | None = None
    currency: str | None = None
    sold_on: date | None = None


@dataclass(frozen=True, slots=True)
class OverlapFlag:
    """An eBay sold listing that also exists as a Gripsweat archive row."""

    listing_id: str
    ebay_url: str
    gripsweat_url: str
    ebay_title: str
    gripsweat_title: str
    ebay_price: Decimal | None
    ebay_currency: str | None
    gripsweat_price: Decimal | None
    gripsweat_currency: str | None
    official_usd: Decimal | None
    official_usd_date: date | None
    ebay_sold_on: date | None
    gripsweat_sold_on: date | None
    flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SoldOverlapReport:
    """Overlap flags plus expected eBay-only sold URLs."""

    overlaps: tuple[OverlapFlag, ...]
    ebay_only: tuple[SoldItem, ...]


def listing_id_from_ebay_sold_url(url: str) -> str:
    """Extract the eBay listing ID from a completed/sold itm URL."""

    match = EBAY_ITM_PATTERN.search(urlparse(str(url or "")).path)
    if match is None:
        return ""
    return match.group("item_id")


def gripsweat_listing_id_from_row(row: Mapping[str, Any]) -> str:
    """Resolve the original marketplace ID from a Gripsweat archive row."""

    stored = str(row.get("original_listing_id") or "").strip()
    if stored:
        return stored

    from_url = gripsweat_original_listing_id(row.get("gripsweat_url"))
    if from_url:
        return from_url

    return str(row.get("gripsweat_item_id") or row.get("gripsweat_item_key") or "").strip()


def parse_sold_card_date(value: Any) -> date | None:
    """Parse headed completed-search ended text such as 'Sold Sep 18, 2026'."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value or "").strip()
    if not text:
        return None

    match = SOLD_CARD_DATE_PATTERN.search(text)
    raw = match.group("date") if match else text
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse_first_usd_price(value: Any) -> Decimal | None:
    """Return a sold-card amount without treating bare $ as official USD."""

    amount, _currency = parse_sold_money(value)
    return amount


def gripsweat_card_amounts(value: Any) -> tuple[Decimal, ...]:
    """Dollar amounts on a Gripsweat card, in print order.

    A Best Offer card prints the original ask, then the accepted amount:
    ``$299.99 $229.00 (USD)``.
    """
    if value is None or value == "":
        return ()
    amounts: list[Decimal] = []
    for match in re.finditer(
        r"(?:US\s*)?\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        str(value),
        flags=re.IGNORECASE,
    ):
        try:
            amounts.append(Decimal(match.group(1).replace(",", "")))
        except InvalidOperation:
            continue
    return tuple(amounts)


def gripsweat_accepted_sold_amount(value: Any) -> Decimal | None:
    """Accepted Gripsweat amount when the card printed ask then sold."""
    amounts = gripsweat_card_amounts(value)
    if len(amounts) < 2:
        return None
    return amounts[-1]


def official_usd_from_gripsweat_row(
    row: Mapping[str, Any],
) -> tuple[Decimal, date | None] | None:
    """Gripsweat sold amount on sold_at is the official transaction-day USD.

    When the card printed two amounts, the later one is the accepted offer
    and the earlier one is the eBay ask.
    """

    accepted = gripsweat_accepted_sold_amount(
        row.get("raw_text") or row.get("card_text")
    )
    if accepted is not None:
        return accepted, as_date(
            row.get("sold_at") or row.get("sold_at_text") or row.get("ended_at")
        )

    amount: Decimal | None = None
    for key in (
        "sold_price",
        "final_price",
        "total_usd",
        "hammer_local",
    ):
        value = row.get(key)
        if value is None or value == "":
            continue
        parsed, _ = parse_sold_money(value)
        if parsed is None:
            continue
        amount = parsed
        break

    if amount is None:
        return None

    return amount, as_date(row.get("sold_at") or row.get("sold_at_text") or row.get("ended_at"))


def gripsweat_currency_from_row(row: Mapping[str, Any]) -> str:
    """Return the Gripsweat archive currency, defaulting blank rows to USD."""

    return str(
        row.get("currency")
        or row.get("currency_display")
        or "USD"
    ).strip().upper() or "USD"


def as_date(value: Any) -> date | None:
    """Normalize warehouse timestamps or dates to a calendar day."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return parse_sold_card_date(value)


def sold_item_from_warehouse_auction(
    row: Mapping[str, Any],
) -> SoldItem | None:
    """Build a sold-item identity from a native warehouse.auction eBay row."""

    listing_id = str(row.get("listing_id") or "").strip()
    url = str(row.get("auction_url") or row.get("url") or "").strip()
    if not listing_id:
        listing_id = listing_id_from_ebay_sold_url(url)
    if not listing_id:
        return None
    if not url:
        url = f"https://www.ebay.com/itm/{listing_id}"
    price = row.get("final_price")
    if price is not None and not isinstance(price, Decimal):
        price = Decimal(str(price))
    currency = str(row.get("currency") or "").strip().upper() or None
    return SoldItem(
        listing_id=listing_id,
        url=url,
        title=str(row.get("title") or ""),
        price_text=str(row.get("final_price") or ""),
        ended_text=str(row.get("ended_at") or ""),
        price=price,
        currency=currency,
        sold_on=as_date(row.get("ended_at")),
    )


def merge_sold_items(
    *groups: Sequence[SoldItem | None],
) -> tuple[SoldItem, ...]:
    """Keep first-seen sold URLs so an artifact comb stays ahead of warehouse extras."""

    merged: list[SoldItem] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            if item is None or item.listing_id in seen:
                continue
            seen.add(item.listing_id)
            merged.append(item)
    return tuple(merged)


def sold_items_from_structured_artifact(
    artifact: Mapping[str, Any],
) -> tuple[SoldItem, ...]:
    """Read completed/sold cards from a headed eBay structured artifact."""

    items: list[SoldItem] = []
    seen: set[str] = set()
    for raw in artifact.get("listings") or ():
        url = str(raw.get("url") or "").strip()
        listing_id = str(
            raw.get("item_id") or raw.get("listing_id") or ""
        ).strip() or listing_id_from_ebay_sold_url(url)
        if not listing_id or listing_id in seen:
            continue
        seen.add(listing_id)
        if not url:
            url = f"https://www.ebay.com/itm/{listing_id}"
        price_text = str(raw.get("price") or "")
        ended_text = str(raw.get("ended") or "")
        amount, currency = parse_sold_money(price_text)
        items.append(
            SoldItem(
                listing_id=listing_id,
                url=url,
                title=str(raw.get("title") or ""),
                price_text=price_text,
                ended_text=ended_text,
                price=amount,
                currency=currency,
                sold_on=parse_sold_card_date(ended_text),
            )
        )
    return tuple(items)


def flag_sold_item_overlaps(
    sold_items: Sequence[SoldItem],
    gripsweat_rows: Iterable[Mapping[str, Any]],
) -> SoldOverlapReport:
    """Flag sold eBay URLs whose listing IDs also exist on Gripsweat.

    Missing Gripsweat coverage is expected and returned as ebay_only.
    """

    gripsweat_by_id: dict[str, Mapping[str, Any]] = {}
    for row in gripsweat_rows:
        listing_id = gripsweat_listing_id_from_row(row)
        if listing_id and listing_id not in gripsweat_by_id:
            gripsweat_by_id[listing_id] = row

    overlaps: list[OverlapFlag] = []
    ebay_only: list[SoldItem] = []

    for item in sold_items:
        row = gripsweat_by_id.get(item.listing_id)
        if row is None:
            ebay_only.append(item)
            continue

        grip_price = row.get("sold_price")
        if grip_price is not None and not isinstance(grip_price, Decimal):
            grip_price = Decimal(str(grip_price))
        grip_currency = gripsweat_currency_from_row(row)
        grip_sold_on = as_date(row.get("sold_at") or row.get("sold_at_text"))
        official = official_usd_from_gripsweat_row(row)
        official_usd = official[0] if official else None
        official_usd_date = official[1] if official else None

        flags = ["overlap"]
        if official_usd is not None:
            flags.append("official_usd_from_gripsweat")
        if grip_currency != "USD":
            flags.append("gripsweat_tagged_non_usd")
        if (
            item.sold_on is not None
            and grip_sold_on is not None
            and item.sold_on != grip_sold_on
        ):
            flags.append("sold_date_mismatch")
        if (
            official_usd is not None
            and item.currency == "USD"
            and item.price is not None
            and item.price != official_usd
        ):
            flags.append("sold_price_mismatch")

        overlaps.append(
            OverlapFlag(
                listing_id=item.listing_id,
                ebay_url=item.url,
                gripsweat_url=str(row.get("gripsweat_url") or ""),
                ebay_title=item.title,
                gripsweat_title=str(row.get("title") or ""),
                ebay_price=item.price,
                ebay_currency=item.currency,
                gripsweat_price=grip_price,
                gripsweat_currency=grip_currency,
                official_usd=official_usd,
                official_usd_date=official_usd_date,
                ebay_sold_on=item.sold_on,
                gripsweat_sold_on=grip_sold_on,
                flags=tuple(flags),
            )
        )

    return SoldOverlapReport(
        overlaps=tuple(overlaps),
        ebay_only=tuple(ebay_only),
    )


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        parsed, _currency = parse_sold_money(value)
        return parsed


def hammer_is_ebay_ask(
    start: Decimal | None,
    hammer: Decimal | None,
) -> bool:
    """True when the stored hammer is missing or just the eBay OBO ask."""
    if hammer is None:
        return True
    if start is None:
        return False
    if hammer == start:
        return True
    delta = abs(hammer - start)
    if delta <= _ASK_HAMMER_DELTA:
        return True
    return bool(start > 0 and delta / start <= _ASK_HAMMER_RATIO)


def gripsweat_should_stamp_obo_hammer(
    *,
    auction_format: str | None,
    start: Decimal | None,
    hammer: Decimal | None,
    gripsweat_amount: Decimal | None,
) -> bool:
    """Gripsweat sold amount fills OBO when eBay only has the original ask."""
    if gripsweat_amount is None:
        return False
    if str(auction_format or "").strip().upper() != "FIXED_PRICE_OBO":
        return False
    return hammer_is_ebay_ask(start, hammer)


def _stamp_sold_money(out: Any, idx: Any, amount: Decimal) -> None:
    hammer, tax, gross, rate = apply_ebay_us_tax(amount, currency="USD")
    assignments = {
        "final_price": hammer,
        "tax_amount": tax,
        "gross_price": gross,
        "tax_rate": rate,
        "price_includes_tax": False if tax is not None else None,
        "final_price_usd": hammer,
        "tax_usd": tax,
        "gross_price_usd": gross,
        "hammer_local": hammer,
        "hammer_usd": hammer,
        "tax_local": tax,
        "tax_usd_display": tax,
        "total_local": gross,
        "total_usd": gross,
        "_official_usd_source": "gripsweat-sold",
    }
    for column, value in assignments.items():
        if column not in out.columns:
            out[column] = None
        out.at[idx, column] = value


def apply_gripsweat_official_usd(
    frame: Any,
    gripsweat_rows_by_listing_id: Mapping[str, Mapping[str, Any]],
) -> Any:
    """eBay ask stays original. Gripsweat sold amounts fill empty OBO hammers."""

    if frame is None or getattr(frame, "empty", True):
        return frame

    out = frame.copy()
    if "_official_usd_source" not in out.columns:
        out["_official_usd_source"] = ""
    if "_gripsweat_usd_reference" not in out.columns:
        out["_gripsweat_usd_reference"] = None

    listing_ids = out["listing_id"].astype(str)
    marketplaces = (
        out["marketplace"].astype(str).str.strip().str.lower()
    )

    for idx in out.index:
        if marketplaces.at[idx] != "ebay":
            continue
        source = gripsweat_rows_by_listing_id.get(
            str(listing_ids.at[idx]).strip()
        )
        if source is None:
            continue
        official = official_usd_from_gripsweat_row(source)
        if official is None:
            continue
        amount, _as_of = official
        out.at[idx, "_gripsweat_usd_reference"] = amount
        start = _decimal_or_none(
            out.at[idx, "start_price"]
            if "start_price" in out.columns
            else None
        )
        hammer = _decimal_or_none(
            out.at[idx, "final_price"]
            if "final_price" in out.columns
            else None
        )
        if hammer is None and "hammer_local" in out.columns:
            hammer = _decimal_or_none(out.at[idx, "hammer_local"])
        auction_format = None
        if "auction_format" in out.columns:
            auction_format = out.at[idx, "auction_format"]
        elif "sale_type" in out.columns:
            auction_format = out.at[idx, "sale_type"]
        if gripsweat_should_stamp_obo_hammer(
            auction_format=None if auction_format is None else str(auction_format),
            start=start,
            hammer=hammer,
            gripsweat_amount=amount,
        ):
            _stamp_sold_money(out, idx, amount)
        else:
            out.at[idx, "_official_usd_source"] = "gripsweat-reference"

    return out


def stamp_gripsweat_obo_hammers(engine: Engine) -> int:
    """Persist Gripsweat sold amounts onto eBay OBO rows that still hold the ask."""
    with engine.begin() as connection:
        ebay_rows = list(
            connection.execute(
                text(
                    """
                    SELECT
                        listing_id,
                        auction_format,
                        start_price,
                        final_price
                    FROM warehouse.auction
                    WHERE marketplace = 'ebay'
                      AND auction_format = 'FIXED_PRICE_OBO'
                    """
                )
            ).mappings()
        )
        gripsweat_rows = list(
            connection.execute(
                text(
                    """
                    SELECT
                        original_listing_id,
                        gripsweat_url,
                        gripsweat_item_id,
                        sold_price,
                        currency,
                        sold_at,
                        raw_text,
                        id
                    FROM warehouse.gripsweat_sale
                    """
                )
            ).mappings()
        )
        by_id: dict[str, Mapping[str, Any]] = {}
        for row in gripsweat_rows:
            listing_id = gripsweat_listing_id_from_row(row)
            if listing_id and listing_id not in by_id:
                by_id[listing_id] = row
        updated = 0
        for row in ebay_rows:
            listing_id = str(row["listing_id"] or "").strip()
            source = by_id.get(listing_id)
            if source is None:
                continue
            official = official_usd_from_gripsweat_row(source)
            if official is None:
                continue
            amount, _as_of = official
            stored = _decimal_or_none(source.get("sold_price"))
            if stored is not None and stored != amount and source.get("id") is not None:
                connection.execute(
                    text(
                        """
                        UPDATE warehouse.gripsweat_sale
                        SET sold_price = :sold_price,
                            updated_at = now()
                        WHERE id = :id
                        """
                    ),
                    {"sold_price": amount, "id": source["id"]},
                )
            start = _decimal_or_none(row.get("start_price"))
            hammer = _decimal_or_none(row.get("final_price"))
            if not gripsweat_should_stamp_obo_hammer(
                auction_format=str(row.get("auction_format") or ""),
                start=start,
                hammer=hammer,
                gripsweat_amount=amount,
            ):
                continue
            sold, tax, gross, rate = apply_ebay_us_tax(amount, currency="USD")
            connection.execute(
                text(
                    """
                    UPDATE warehouse.auction
                    SET final_price = :hammer,
                        tax_amount = :tax,
                        gross_price = :gross,
                        tax_rate = :rate,
                        price_includes_tax = FALSE,
                        final_price_usd = :hammer,
                        tax_usd = :tax,
                        gross_price_usd = :gross
                    WHERE marketplace = 'ebay'
                      AND listing_id = :listing_id
                    """
                ),
                {
                    "hammer": sold,
                    "tax": tax,
                    "gross": gross,
                    "rate": rate,
                    "listing_id": listing_id,
                },
            )
            updated += 1
        return updated

