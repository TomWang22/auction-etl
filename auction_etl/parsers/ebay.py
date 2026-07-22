from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup
from bs4 import Tag


_ITEM_ID_RE = re.compile(r"/itm/(\d+)")
_POSITIVE_RE = re.compile(r"(\d+)%\s*positive", re.I)
_FEEDBACK_RE = re.compile(r"\(([\d,]+)\)")
_BIDS_RE = re.compile(r"(\d+)\s+bids?", re.I)


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None

    value = value.replace("\xa0", " ")
    value = value.replace("Opens in a new window or tab", "")
    value = re.sub(r"\s+", " ", value)

    value = value.strip()

    return value or None


def first_text(node: Tag | None, selector: str) -> str | None:
    if node is None:
        return None

    element = node.select_one(selector)

    if element is None:
        return None

    return clean_text(element.get_text(" ", strip=True))


def first_attr(node: Tag | None, selector: str, attr: str) -> str | None:
    if node is None:
        return None

    element = node.select_one(selector)

    if element is None:
        return None

    value = element.get(attr)

    if not value:
        return None

    return str(value)


def parse_item_id(card: Tag) -> str | None:
    listing_id = card.get("data-listingid")

    if listing_id:
        return str(listing_id)

    href = first_attr(card, "a.s-card__link[href]", "href")

    if not href:
        return None

    match = _ITEM_ID_RE.search(href)

    if not match:
        return None

    return match.group(1)


def parse_url(card: Tag) -> str | None:
    href = first_attr(card, "a.s-card__link[href]", "href")

    if not href:
        return None

    return href.split("?", 1)[0]


def parse_title(card: Tag) -> str | None:
    title = first_text(card, ".s-card__title")

    if not title:
        return None

    if title.lower().startswith("shop on ebay"):
        return None

    return title


def parse_subtitle(card: Tag) -> str | None:
    return first_text(card, ".s-card__subtitle")


def parse_image(card: Tag) -> str | None:
    return first_attr(card, "img.s-card__image", "src")


def parse_ended(card: Tag) -> str | None:
    return first_text(card, ".s-card__caption")


def parse_attribute_rows(card: Tag) -> list[str]:
    rows: list[str] = []

    for row in card.select(".su-card-container__attributes__primary .s-card__attribute-row"):
        text = clean_text(row.get_text(" ", strip=True))

        if text:
            rows.append(text)

    return rows


def parse_price(rows: list[str]) -> str | None:
    for row in rows:
        if "$" in row or "£" in row or "€" in row:
            if "delivery" not in row.lower():
                return row

    return None


def parse_shipping(rows: list[str]) -> str | None:
    for row in rows:
        lower = row.lower()

        if "delivery" in lower:
            return row

        if "shipping" in lower:
            return row

        if "free" in lower:
            return row

    return None


def parse_bid_text(rows: list[str]) -> str | None:
    for row in rows:
        if _BIDS_RE.search(row):
            return row

    return None


def parse_sale_type(rows: list[str]) -> str:
    bid = parse_bid_text(rows)

    if bid is None:
        return "FIXED_PRICE"

    return "AUCTION"


def parse_location(rows: list[str]) -> str | None:
    for row in rows:
        if row.lower().startswith("located in"):
            return row.replace("Located in", "").strip()

    return None


def parse_seller(card: Tag) -> tuple[str | None, str |None]:
    secondary = card.select_one(
        ".su-card-container__attributes__secondary"
    )

    if secondary is None:
        return None, None

    texts = [
        clean_text(span.get_text(" ", strip=True))
        for span in secondary.select("span")
    ]

    texts = [t for t in texts if t]

    if not texts:
        return None, None

    seller = texts[0]

    feedback = texts[1] if len(texts) > 1 else None

    return seller, feedback


def build_payload(card: Tag) -> dict[str, Any]:
    return {
        "html": str(card),
    }


def is_listing(card: Tag) -> bool:
    if not card.get("data-listingid"):
        return False

    title = parse_title(card)

    if not title:
        return False

    return True

def parse_search(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")

    listings: list[dict[str, Any]] = []

    for card in soup.select("li.s-card[data-listingid]"):
        if not is_listing(card):
            continue

        item_id = parse_item_id(card)

        if not item_id:
            continue

        rows = parse_attribute_rows(card)

        seller, seller_feedback = parse_seller(card)

        listings.append(
            {
                "item_id": item_id,
                "url": parse_url(card),
                "title": parse_title(card),
                "subtitle": parse_subtitle(card),
                "price": parse_price(rows),
                "shipping": parse_shipping(rows),
                "bids": parse_bid_text(rows),
                "sale_type": parse_sale_type(rows),
                "location": parse_location(rows),
                "seller": seller,
                "seller_feedback": seller_feedback,
                "condition": parse_subtitle(card),
                "ended": parse_ended(card),
                "image_url": parse_image(card),
                "payload": build_payload(card),
            }
        )

    return listings


def next_page(html: str, current_url: str | None = None) -> str | None:
    soup = BeautifulSoup(html, "html.parser")

    selectors = (
        'a[rel="next"]',
        'a[aria-label="Go to next search page"]',
        'a[aria-label="Next page"]',
        'a.pagination__next',
        'a[type="next"]',
    )

    for selector in selectors:
        link = soup.select_one(selector)

        if link is None:
            continue

        href = link.get("href")

        if href:
            return href

    return None

