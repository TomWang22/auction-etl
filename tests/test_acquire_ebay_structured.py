"""Tests for the DB-free structured eBay acquisition producer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auction_etl.collectors.ebay_compat import (
    EbayListing,
    render_search_page,
)
from scripts.acquire_ebay_structured import (
    EbayAcquisitionError,
    atomic_write_json,
    build_payload_from_html,
    canonical_listings,
    collector_url_for_source,
    is_access_block_status,
    is_ebay_url,
    is_signin_url,
)


ROOT = Path(__file__).resolve().parents[1]
PRODUCER = ROOT / "scripts" / "acquire_ebay_structured.py"


@pytest.mark.parametrize(
    "status",
    [
        401,
        403,
        429,
    ],
)
def test_access_block_statuses_fail_closed(
    status: int,
) -> None:
    """Recognize explicit eBay HTTP access blocks."""

    assert is_access_block_status(
        status
    ) is True


@pytest.mark.parametrize(
    "status",
    [
        None,
        200,
        301,
        404,
        500,
    ],
)
def test_other_statuses_are_not_access_block_classification(
    status: int | None,
) -> None:
    """Do not misclassify unrelated HTTP outcomes."""

    assert is_access_block_status(
        status
    ) is False


def test_ebay_url_validation() -> None:
    """Accept eBay HTTPS URLs and reject unrelated hosts."""

    assert is_ebay_url(
        "https://www.ebay.com/sch/i.html"
    )
    assert is_ebay_url(
        "https://www.ebay.co.uk/sch/i.html"
    )
    assert not is_ebay_url(
        "http://www.ebay.com/sch/i.html"
    )
    assert not is_ebay_url(
        "https://example.com/ebay"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://signin.ebay.com/ws/eBayISAPI.dll",
        "https://www.ebay.com/signin/",
        "https://www.ebay.co.uk/signin",
    ],
)
def test_signin_urls_are_detected(
    url: str,
) -> None:
    """Classify eBay authentication redirects before parsing."""

    assert is_signin_url(
        url
    ) is True


def test_collector_url_encodes_source_name() -> None:
    """Build the raw-page namespace expected by the refresh handoff."""

    assert (
        collector_url_for_source(
            "face records"
        )
        == "collector://ebay/face%20records"
    )


def test_canonical_listings_deduplicate_identical_records() -> None:
    """Collapse identical duplicate item identities deterministically."""

    records = [
        {
            "item_id": "188586715117",
            "url": "https://www.ebay.com/itm/188586715117",
            "title": "Teresa Teng LP",
        },
        {
            "item_id": "188586715117",
            "url": "https://www.ebay.com/itm/188586715117",
            "title": "Teresa Teng LP",
        },
    ]

    assert canonical_listings(
        records
    ) == [
        {
            "item_id": "188586715117",
            "url": "https://www.ebay.com/itm/188586715117",
            "title": "Teresa Teng LP",
        }
    ]


def test_canonical_listings_reject_conflicting_identity() -> None:
    """Never silently merge contradictory records for one item ID."""

    records = [
        {
            "item_id": "188586715117",
            "url": "https://www.ebay.com/itm/188586715117",
            "title": "First title",
        },
        {
            "item_id": "188586715117",
            "url": "https://www.ebay.com/itm/188586715117",
            "title": "Different title",
        },
    ]

    with pytest.raises(
        EbayAcquisitionError,
        match="Conflicting duplicate",
    ):
        canonical_listings(
            records
        )


def test_compatibility_parser_roundtrip() -> None:
    """Reuse the established parser contract for producer output."""

    html = render_search_page(
        [
            EbayListing(
                item_id="188586715117",
                url=(
                    "https://www.ebay.com/"
                    "itm/188586715117"
                ),
                title="Teresa Teng LP",
                price="$42.00",
                shipping="$5.00 shipping",
                bids="3 bids",
                location="Japan",
                seller="facerecords",
                seller_feedback="99.8% positive",
                subtitle="Used",
                ended="Sold Aug 26, 2026",
                image_url="https://example.com/item.jpg",
            )
        ]
    )

    payload = build_payload_from_html(
        html=html,
        source_name="facerecords",
        requested_url=(
            "https://www.ebay.com/"
            "sch/i.html?_ssn=facerecords"
        ),
        final_url=(
            "https://www.ebay.com/"
            "sch/i.html?_ssn=facerecords"
        ),
        http_status=200,
        item_link_count=1,
        collected_at_utc="2026-08-27T22:30:00Z",
    )

    assert payload["schema"] == (
        "auction-etl/ebay-structured-acquisition/v1"
    )
    assert payload["collector_url"] == (
        "collector://ebay/facerecords"
    )
    assert payload["listing_count"] == 1

    listings = payload["listings"]

    assert isinstance(
        listings,
        list,
    )

    listing = listings[0]

    assert listing["item_id"] == "188586715117"
    assert listing["title"] == "Teresa Teng LP"
    assert listing["seller"] == "facerecords"


def test_atomic_write_json(
    tmp_path: Path,
) -> None:
    """Write one deterministic JSON artifact without partial output."""

    output = (
        tmp_path
        / "facerecords.json"
    )

    payload = {
        "schema": "test/v1",
        "listings": [
            {
                "item_id": "188586715117",
                "url": "https://www.ebay.com/itm/188586715117",
                "title": "Example",
            }
        ],
    }

    atomic_write_json(
        output,
        payload,
    )

    assert json.loads(
        output.read_text(
            encoding="utf-8"
        )
    ) == payload

    assert list(
        tmp_path.glob(
            ".*.tmp"
        )
    ) == []


def test_producer_has_no_database_or_scroll_path() -> None:
    """Keep acquisition isolated from DB writes and scrolling behavior."""

    source = PRODUCER.read_text(
        encoding="utf-8"
    )

    forbidden = (
        "SessionLocal",
        "DATABASE_URL",
        "warehouse.auction",
        "staging.listing",
        "mouse.wheel",
        "scrollBy",
        "scrollTo",
        "--disable-dev-shm-usage",
    )

    for fragment in forbidden:
        assert fragment not in source


def test_producer_checks_http_block_before_result_wait() -> None:
    """Explicit HTTP blocking must precede item-link waiting."""

    source = PRODUCER.read_text(
        encoding="utf-8"
    )

    block_index = source.index(
        "is_access_block_status("
    )
    wait_index = source.index(
        ").first.wait_for(",
        block_index,
    )

    assert block_index < wait_index
