from __future__ import annotations

import re
from decimal import Decimal
from decimal import ROUND_CEILING
from typing import Any
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

from bs4 import BeautifulSoup
from bs4.element import Tag


_AUCTION_ID_RE = re.compile(
    r"/auction/([^/?#]+)",
    re.IGNORECASE,
)

_GROSS_PRICE_RE = re.compile(
    r"([0-9][0-9,]*)\s*YEN",
    re.IGNORECASE,
)

_DISPLAYED_USD_RE = re.compile(
    r"US\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
    re.IGNORECASE,
)

_EXPLICIT_TAX_RE = re.compile(
    r"Tax\s*([0-9][0-9,]*)\s*yen",
    re.IGNORECASE,
)

_INCLUDED_TAX_RE = re.compile(
    r"Price\s+including\s+Tax",
    re.IGNORECASE,
)

_TAX_RATE = Decimal("0.10")
_TAX_MULTIPLIER = Decimal("1.10")


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = re.sub(
        r"\s+",
        " ",
        value.replace("\xa0", " "),
    ).strip()

    return cleaned or None


def canonical_url(value: str | None) -> str | None:
    if not value:
        return None

    if value.startswith("/"):
        value = f"https://buyee.jp{value}"

    parts = urlsplit(value)

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            "",
            "",
        )
    )


def first_text(
    node: Tag,
    selector: str,
) -> str | None:
    element = node.select_one(selector)

    if element is None:
        return None

    return clean_text(
        element.get_text(
            " ",
            strip=True,
        )
    )


def first_attr(
    node: Tag,
    selector: str,
    attribute: str,
) -> str | None:
    element = node.select_one(selector)

    if element is None:
        return None

    value = element.get(attribute)

    return str(value) if value else None


def labeled_value(
    card: Tag,
    label: str,
) -> str | None:
    wanted = label.casefold()

    for item in card.select(".itemCard__infoItem"):
        title = first_text(item, ".g-title")

        if title and title.casefold() == wanted:
            return first_text(item, ".g-text")

    return None


def parse_url(card: Tag) -> str | None:
    href = first_attr(
        card,
        "a.wl_item_title[href]",
        "href",
    )

    if not href:
        href = first_attr(
            card,
            "a[href*='/auction/']",
            "href",
        )

    return canonical_url(href)


def parse_item_id(
    card: Tag,
    auction_url: str | None,
) -> str | None:
    data_id = card.get("data-id")

    if data_id:
        return str(data_id)

    if auction_url:
        match = _AUCTION_ID_RE.search(auction_url)

        if match:
            return match.group(1)

    watchlist_id = card.get("data-wid")

    return str(watchlist_id) if watchlist_id else None


def parse_title(card: Tag) -> str | None:
    title = first_text(card, "a.wl_item_title")

    if title:
        return title

    return clean_text(
        first_attr(
            card,
            "img[alt]",
            "alt",
        )
    )


def parse_price_details(card: Tag) -> dict[str, Any]:
    text = first_text(card, ".g-price")

    result: dict[str, Any] = {
        "display_text": text,
        "currency": "JPY",
        "tax_rate": None,
        "price_includes_tax": None,
        "hammer_price_jpy": None,
        "tax_amount_jpy": None,
        "gross_price_jpy": None,
        "displayed_usd": None,
    }

    if not text:
        return result

    gross_match = _GROSS_PRICE_RE.search(text)

    if gross_match is None:
        return result

    gross = Decimal(
        gross_match.group(1).replace(",", "")
    )

    result["gross_price_jpy"] = str(gross)

    usd_match = _DISPLAYED_USD_RE.search(text)

    if usd_match:
        result["displayed_usd"] = str(
            Decimal(
                usd_match.group(1).replace(",", "")
            )
        )

    explicit_tax_match = _EXPLICIT_TAX_RE.search(text)

    if explicit_tax_match:
        tax = Decimal(
            explicit_tax_match.group(1).replace(",", "")
        )

        result["tax_amount_jpy"] = str(tax)
        result["hammer_price_jpy"] = str(gross - tax)
        result["price_includes_tax"] = tax > 0
        result["tax_rate"] = (
            "0.10"
            if tax > 0
            else "0.00"
        )

        return result

    if _INCLUDED_TAX_RE.search(text):
        hammer = (
            gross / _TAX_MULTIPLIER
        ).to_integral_value(
            rounding=ROUND_CEILING
        )
        tax = gross - hammer

        result["hammer_price_jpy"] = str(hammer)
        result["tax_amount_jpy"] = str(tax)
        result["price_includes_tax"] = True
        result["tax_rate"] = str(_TAX_RATE)

        return result

    result["hammer_price_jpy"] = str(gross)

    return result


def parse_ended(card: Tag) -> str | None:
    labels = (
        "End Time",
        "Auction Ended",
        "End Date",
        "Closing Time",
        "終了日時",
        "終了時間",
        "終了日",
    )

    for label in labels:
        value = labeled_value(
            card,
            label,
        )

        if value:
            return value

    selectors = (
        ".itemCard__endTime",
        ".itemCard__closedDate",
        ".auctionEndTime",
        "[data-end-time]",
        "time[datetime]",
    )

    for selector in selectors:
        element = card.select_one(selector)

        if element is None:
            continue

        datetime_value = element.get(
            "datetime"
        )

        if datetime_value:
            return str(datetime_value)

        data_value = element.get(
            "data-end-time"
        )

        if data_value:
            return str(data_value)

        value = clean_text(
            element.get_text(
                " ",
                strip=True,
            )
        )

        if value:
            return value

    return None


def parse_bids(card: Tag) -> str | None:
    return labeled_value(
        card,
        "Number of Bids",
    )


def parse_seller(card: Tag) -> str | None:
    return labeled_value(
        card,
        "Seller",
    )


def parse_image(card: Tag) -> str | None:
    return first_attr(
        card,
        "img.g-thumbnail__image",
        "src",
    ) or first_attr(
        card,
        "img[src]",
        "src",
    )


def parse_search(
    html: str,
) -> list[dict[str, Any]]:
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    listings: list[dict[str, Any]] = []

    cards = list(
        soup.select(
            "li.js-item.itemCard[data-wid], "
            "li.itemCard[data-wid]"
        )
    )

    for card in cards:
        auction_url = parse_url(card)
        item_id = parse_item_id(
            card,
            auction_url,
        )

        if not item_id or not auction_url:
            continue

        price_details = parse_price_details(card)

        listings.append(
            {
                "item_id": item_id,
                "watchlist_id": (
                    str(card.get("data-wid"))
                    if card.get("data-wid")
                    else None
                ),
                "url": auction_url,
                "title": parse_title(card),
                "subtitle": None,
                "description": None,
                "price": price_details["gross_price_jpy"],
                "price_text": price_details["display_text"],
                "shipping": None,
                "bids": parse_bids(card),
                "sale_type": "AUCTION",
                "location": None,
                "seller": parse_seller(card),
                "feedback": None,
                "condition": None,
                "ended": parse_ended(card),
                "image": parse_image(card),
                "payload": {
                    "html": str(card),
                    "watchlist_id": (
                        str(card.get("data-wid"))
                        if card.get("data-wid")
                        else None
                    ),
                    "notification": (
                        str(card.get("data-notification"))
                        if card.get("data-notification")
                        else None
                    ),
                    "price_details": price_details,
                },
            }
        )

    return listings
