"""Parse Yahoo!フリマ sold-search HTML (__NEXT_DATA__)."""

from __future__ import annotations

import json
import re
from typing import Any

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)

_ITEM_URL = "https://paypayfleamarket.yahoo.co.jp/item/{item_id}"


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


def _search_result(data: dict[str, Any]) -> dict[str, Any] | None:
    try:
        result = data["props"]["initialState"]["searchState"]["search"][
            "result"
        ]
    except (KeyError, TypeError):
        return None
    return result if isinstance(result, dict) else None


def parse_sold_card(item: dict[str, Any]) -> dict[str, Any] | None:
    """Map one フリマ search card. Requires SOLD status when present."""

    item_id = str(item.get("id") or "").strip()
    if not item_id:
        return None

    status = item.get("itemStatus")
    if status is not None and str(status).upper() != "SOLD":
        return None

    price = item.get("price")
    if not isinstance(price, (int, float)):
        return None

    seller = item.get("seller") if isinstance(item.get("seller"), dict) else {}

    sold = int(price)
    return {
        "marketplace": "yahoo_fleamarket",
        "listing_id": item_id,
        "title": str(item.get("title") or "").strip() or None,
        "currency": "JPY",
        # No tax markers on sold search or item detail samples — hammer only.
        "start_price_jpy": None,
        "bid_count": None,
        "gross_price_jpy": sold,
        "final_price_jpy": sold,
        "tax_amount_jpy": None,
        "tax_rate": None,
        "price_includes_tax": None,
        "closing_at": item.get("endTime"),
        "open_at": item.get("openTime"),
        "image_url": item.get("thumbnailImageUrl"),
        "seller_id": item.get("sellerId") or seller.get("id"),
        "condition": item.get("condition"),
        "item_status": status,
        "auction_url": _ITEM_URL.format(item_id=item_id),
    }


def parse_sold_search_html(html: str) -> dict[str, Any]:
    """Parse a sold-search page. Ignores embedded auction promo modules."""

    data = extract_next_data(html)
    if data is None:
        return {
            "items": [],
            "total_results_available": None,
            "offset": None,
            "parse_ok": False,
        }

    result = _search_result(data)
    if result is None:
        return {
            "items": [],
            "total_results_available": None,
            "offset": None,
            "parse_ok": False,
        }

    raw_items = result.get("items")
    if not isinstance(raw_items, list):
        raw_items = []

    rows: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        parsed = parse_sold_card(item)
        if parsed is not None:
            rows.append(parsed)

    total = result.get("totalResultsAvailable")
    offset = result.get("offset")

    return {
        "items": rows,
        "total_results_available": total if isinstance(total, int) else None,
        "offset": offset if isinstance(offset, int) else None,
        "parse_ok": True,
    }


def parse_item_detail_html(html: str) -> dict[str, Any] | None:
    """Parse one フリマ item page for id / sold price (no tax fields expected)."""

    data = extract_next_data(html)
    if data is None:
        return None

    item: Any = None
    for path in (
        ("props", "initialState", "itemsState", "items", "item"),
        ("props", "pageProps", "initialState", "itemsState", "items", "item"),
    ):
        node: Any = data
        try:
            for key in path:
                node = node[key]
            if isinstance(node, dict):
                item = node
                break
        except (KeyError, TypeError):
            continue

    if item is None:
        return None

    item_id = str(item.get("id") or "").strip()
    if not item_id:
        return None

    price = item.get("price")
    if not isinstance(price, (int, float)):
        return None

    sold = int(price)
    return {
        "marketplace": "yahoo_fleamarket",
        "listing_id": item_id,
        "currency": "JPY",
        "gross_price_jpy": sold,
        "final_price_jpy": sold,
        "tax_amount_jpy": None,
        "price_includes_tax": None,
        "item_status": item.get("status"),
        "auction_url": _ITEM_URL.format(item_id=item_id),
    }
