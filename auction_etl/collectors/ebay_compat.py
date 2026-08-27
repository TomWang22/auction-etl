"""Build parser-compatible eBay HTML from structured listing records."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Iterable


@dataclass(frozen=True, slots=True)
class EbayListing:
    """Structured eBay listing accepted by the compatibility adapter."""

    item_id: str
    url: str
    title: str
    price: str | None = None
    shipping: str | None = None
    bids: str | None = None
    location: str | None = None
    seller: str | None = None
    seller_feedback: str | None = None
    subtitle: str | None = None
    ended: str | None = None
    image_url: str | None = None


def _text(value: str | None) -> str:
    """Escape optional text for HTML output."""
    return escape(
        value or "",
        quote=True,
    )


def _attribute_row(value: str | None) -> str:
    """Render one parser-compatible primary attribute row."""
    if not value:
        return ""

    return (
        '<div class="s-card__attribute-row">'
        f"{_text(value)}"
        "</div>"
    )


def _seller_block(listing: EbayListing) -> str:
    """Render the parser-compatible seller metadata block."""
    if not listing.seller and not listing.seller_feedback:
        return ""

    values = (
        listing.seller,
        listing.seller_feedback,
    )

    spans = "".join(
        f"<span>{_text(value)}</span>"
        for value in values
        if value
    )

    return (
        '<div class="su-card-container__attributes__secondary">'
        f"{spans}"
        "</div>"
    )


def render_listing_card(listing: EbayListing) -> str:
    """Render one listing using the existing eBay parser DOM contract."""
    item_id = listing.item_id.strip()
    title = listing.title.strip()
    url = listing.url.strip()

    if not item_id:
        raise ValueError(
            "eBay item_id must not be empty."
        )

    if not title:
        raise ValueError(
            "eBay title must not be empty."
        )

    if not url:
        raise ValueError(
            "eBay URL must not be empty."
        )

    primary_rows = "".join(
        (
            _attribute_row(listing.price),
            _attribute_row(listing.shipping),
            _attribute_row(listing.bids),
            _attribute_row(
                (
                    f"Located in {listing.location}"
                    if listing.location
                    else None
                )
            ),
        )
    )

    subtitle = (
        (
            '<div class="s-card__subtitle">'
            f"{_text(listing.subtitle)}"
            "</div>"
        )
        if listing.subtitle
        else ""
    )

    ended = (
        (
            '<div class="s-card__caption">'
            f"{_text(listing.ended)}"
            "</div>"
        )
        if listing.ended
        else ""
    )

    image = (
        (
            '<img class="s-card__image" '
            f'src="{_text(listing.image_url)}">'
        )
        if listing.image_url
        else ""
    )

    return (
        f'<li class="s-card" data-listingid="{_text(item_id)}">'
        f'<a class="s-card__link" href="{_text(url)}">'
        f'<div class="s-card__title">{_text(title)}</div>'
        "</a>"
        f"{subtitle}"
        f"{image}"
        f"{ended}"
        '<div class="su-card-container__attributes__primary">'
        f"{primary_rows}"
        "</div>"
        f"{_seller_block(listing)}"
        "</li>"
    )


def render_search_page(
    listings: Iterable[EbayListing],
) -> str:
    """Render structured eBay listings as one parser-compatible page."""
    cards = "".join(
        render_listing_card(listing)
        for listing in listings
    )

    return (
        "<!doctype html>"
        '<html lang="en">'
        "<head>"
        '<meta charset="utf-8">'
        "<title>eBay collector compatibility page</title>"
        "</head>"
        "<body>"
        "<ul>"
        f"{cards}"
        "</ul>"
        "</body>"
        "</html>"
    )
