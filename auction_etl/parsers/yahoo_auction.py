"""Parse Yahoo!オークション closedsearch / item HTML (__NEXT_DATA__)."""

from __future__ import annotations

import json
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)

_AUCTION_ITEM_URL = "https://auctions.yahoo.co.jp/jp/auction/{auction_id}"
_TAX_DIVISOR = Decimal("1.1")
_TAX_RATE = Decimal("0.10")


def extract_next_data(html: str) -> dict[str, Any] | None:
    """Return parsed `__NEXT_DATA__` JSON, or None if missing/invalid."""

    match = _NEXT_DATA_RE.search(html or "")
    if match is None:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _listing_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        items = (
            data["props"]["pageProps"]["initialState"]["search"]["items"][
                "listing"
            ]["items"]
        )
    except (KeyError, TypeError):
        try:
            items = data["props"]["initialState"]["search"]["items"][
                "listing"
            ]["items"]
        except (KeyError, TypeError):
            return []
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _total_results_available(data: dict[str, Any]) -> int | None:
    for path in (
        ("props", "pageProps", "initialState", "search", "items", "listing"),
        ("props", "initialState", "search", "items", "listing"),
    ):
        node: Any = data
        try:
            for key in path:
                node = node[key]
            total = node.get("totalResultsAvailable")
            if isinstance(total, int):
                return total
        except (KeyError, TypeError, AttributeError):
            continue
    return None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _yen(value: int) -> Decimal:
    return Decimal(value).quantize(Decimal("1"))


def money_from_closedsearch_card(item: dict[str, Any]) -> dict[str, Any]:
    """Hammer / start / bids / tax from a closedsearch card.

    Displayed winning price is ``price`` (matches the auction page hammer,
    e.g. 43,018 with ``(Tax 0 yen)`` when ``taxFlag=0``).

    When ``taxFlag=1``, ``price`` is tax-inclusive (税込); prefer
    ``initPriceNoTax`` as the ex-tax adjusted hammer, else ``price / 1.1``.
    """

    gross = _as_int(item.get("price"))
    start = _as_int(item.get("initPriceNoTax"))
    tax_flag = _as_int(item.get("taxFlag")) or 0
    bids = _as_int(item.get("bidCount"))

    if gross is None:
        return {
            "start_price_jpy": start,
            "bid_count": bids,
            "gross_price_jpy": None,
            "final_price_jpy": None,
            "tax_amount_jpy": None,
            "tax_rate": None,
            "price_includes_tax": None,
            "tax_flag": tax_flag,
        }

    if tax_flag == 1:
        # Displayed ``price`` is 税込. ``initPriceNoTax`` is only the ex-tax
        # hammer when it matches price/1.1 (common on fixed-price cards).
        # Otherwise it is the auction start (often ¥1) — do not treat as hammer.
        adjusted = int(
            (_yen(gross) / _TAX_DIVISOR).to_integral_value(
                rounding=ROUND_HALF_UP
            )
        )
        if start is not None and abs(start - adjusted) <= 1:
            adjusted = start
        tax_amount = gross - adjusted
        return {
            "start_price_jpy": start,
            "bid_count": bids,
            "gross_price_jpy": gross,
            "final_price_jpy": adjusted,
            "tax_amount_jpy": tax_amount,
            "tax_rate": _TAX_RATE,
            "price_includes_tax": True,
            "tax_flag": tax_flag,
        }

    # Tax 0 yen on the detail page: hammer stands alone.
    return {
        "start_price_jpy": start,
        "bid_count": bids,
        "gross_price_jpy": gross,
        "final_price_jpy": gross,
        "tax_amount_jpy": 0,
        "tax_rate": None,
        "price_includes_tax": False,
        "tax_flag": tax_flag,
    }


def parse_closedsearch_card(item: dict[str, Any]) -> dict[str, Any] | None:
    """Map one closedsearch listing item. Drops フリマ embeds."""

    if bool(item.get("isFleamarketItem")):
        return None

    auction_id = str(item.get("auctionId") or "").strip()
    if not auction_id:
        return None

    money = money_from_closedsearch_card(item)
    if money["gross_price_jpy"] is None:
        return None

    seller = item.get("seller") if isinstance(item.get("seller"), dict) else {}

    return {
        "marketplace": "yahoo_auction",
        "listing_id": auction_id,
        "title": str(item.get("title") or "").strip() or None,
        "currency": "JPY",
        "closing_at": item.get("endTime"),
        "start_at": item.get("startTime"),
        "image_url": item.get("imageUrl"),
        "seller_id": seller.get("userId"),
        "condition": item.get("itemCondition"),
        "is_fixed_price": bool(item.get("isFixedPrice")),
        "auction_url": _AUCTION_ITEM_URL.format(auction_id=auction_id),
        **money,
    }


def parse_closedsearch_html(html: str) -> dict[str, Any]:
    """Parse a closedsearch results page into sale rows + paging hints."""

    data = extract_next_data(html)
    if data is None:
        return {
            "items": [],
            "total_results_available": None,
            "parse_ok": False,
        }

    rows: list[dict[str, Any]] = []
    for item in _listing_items(data):
        parsed = parse_closedsearch_card(item)
        if parsed is not None:
            rows.append(parsed)

    return {
        "items": rows,
        "total_results_available": _total_results_available(data),
        "parse_ok": True,
    }


def parse_item_detail_html(html: str) -> dict[str, Any] | None:
    """Parse one auction item page for price / tax-inclusive fields."""

    data = extract_next_data(html)
    if data is None:
        return None

    detail: Any = None
    for path in (
        ("props", "pageProps", "initialState", "item", "detail", "item"),
        ("props", "initialState", "item", "detail", "item"),
    ):
        node: Any = data
        try:
            for key in path:
                node = node[key]
            if isinstance(node, dict):
                detail = node
                break
        except (KeyError, TypeError):
            continue

    if detail is None:
        return None

    auction_id = str(detail.get("auctionId") or "").strip()
    if not auction_id:
        return None

    price = _as_int(detail.get("price"))
    taxin = _as_int(detail.get("taxinPrice"))
    tax_rate = detail.get("taxRate")
    init_price = _as_int(detail.get("initPrice"))
    bids = _as_int(detail.get("bidCount"))

    if taxin is not None and price is not None:
        gross = taxin
        adjusted = price
        tax_amount = gross - adjusted
        includes = True
        rate = (
            Decimal(str(tax_rate)) / Decimal("100")
            if isinstance(tax_rate, (int, float))
            else _TAX_RATE
        )
    else:
        gross = price
        adjusted = price
        tax_amount = 0 if price is not None else None
        includes = False
        rate = None

    return {
        "marketplace": "yahoo_auction",
        "listing_id": auction_id,
        "currency": "JPY",
        "start_price_jpy": init_price,
        "bid_count": bids,
        "gross_price_jpy": gross,
        "final_price_jpy": adjusted,
        "tax_amount_jpy": tax_amount,
        "tax_rate": rate,
        "price_includes_tax": includes,
        "auction_url": _AUCTION_ITEM_URL.format(auction_id=auction_id),
    }
