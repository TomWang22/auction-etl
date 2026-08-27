"""Tests for structured eBay compatibility with the existing parser."""

from __future__ import annotations

import pytest

from auction_etl.collectors.ebay_compat import (
    EbayListing,
    render_search_page,
)
from auction_etl.parsers.ebay import parse_search


def test_structured_listing_round_trips_through_existing_parser() -> None:
    """Preserve the existing eBay parser contract."""
    html = render_search_page(
        [
            EbayListing(
                item_id="188586715117",
                url="https://www.ebay.com/itm/188586715117",
                title="Teresa Teng LP",
                subtitle="Used",
                price="$42.00",
                shipping="$5.00 shipping",
                bids="3 bids",
                location="Japan",
                seller="facerecords",
                seller_feedback="99.8% positive",
                ended="Sold Aug 26, 2026",
                image_url="https://example.com/item.jpg",
            )
        ]
    )

    listings = parse_search(html)

    assert len(listings) == 1

    listing = listings[0]

    assert listing["item_id"] == "188586715117"
    assert listing["url"] == "https://www.ebay.com/itm/188586715117"
    assert listing["title"] == "Teresa Teng LP"
    assert listing["subtitle"] == "Used"
    assert listing["price"] == "$42.00"
    assert listing["shipping"] == "$5.00 shipping"
    assert listing["bids"] == "3 bids"
    assert listing["sale_type"] == "AUCTION"
    assert listing["location"] == "Japan"
    assert listing["seller"] == "facerecords"
    assert listing["seller_feedback"] == "99.8% positive"
    assert listing["ended"] == "Sold Aug 26, 2026"
    assert listing["image_url"] == "https://example.com/item.jpg"


def test_fixed_price_listing_has_no_bid_row() -> None:
    """Keep fixed-price semantics compatible with the existing parser."""
    html = render_search_page(
        [
            EbayListing(
                item_id="123456789012",
                url="https://www.ebay.com/itm/123456789012",
                title="Teresa Teng CD",
                price="$18.00",
                seller="facerecords",
            )
        ]
    )

    listing = parse_search(html)[0]

    assert listing["sale_type"] == "FIXED_PRICE"
    assert listing["bids"] is None


def test_required_identity_fields_are_validated() -> None:
    """Reject records that cannot become valid existing-parser listings."""
    invalid = EbayListing(
        item_id="",
        url="https://www.ebay.com/itm/1",
        title="Example",
    )

    with pytest.raises(
        ValueError,
        match="eBay item_id must not be empty",
    ):
        render_search_page(
            [invalid]
        )
