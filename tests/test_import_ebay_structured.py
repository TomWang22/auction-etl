"""Tests for structured eBay raw-page importing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from auction_etl.collectors.ebay_compat import EbayListing
from auction_etl.parsers.ebay import parse_search
from scripts.import_ebay_structured import (
    StructuredEbayImportError,
    load_listings,
    persist_listings,
    sha256_text,
)


class FakeSession:
    """Minimal SQLAlchemy-session substitute for persistence tests."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flush_count = 0
        self.commit_count = 0

    def add(
        self,
        value: Any,
    ) -> None:
        """Record one added ORM object."""
        self.added.append(
            value
        )

    def flush(self) -> None:
        """Simulate generated primary keys."""
        self.flush_count += 1

        for index, value in enumerate(
            self.added,
            start=1,
        ):
            if getattr(
                value,
                "id",
                None,
            ) is None:
                value.id = index

    def commit(self) -> None:
        """Record one transaction commit."""
        self.commit_count += 1


def sample_payload() -> list[dict[str, object]]:
    """Return one representative structured eBay payload."""
    return [
        {
            "item_id": "188586715117",
            "url": "https://www.ebay.com/itm/188586715117",
            "title": "Teresa Teng LP",
            "subtitle": "Used",
            "price": "$42.00",
            "shipping": "$5.00 shipping",
            "bids": "3 bids",
            "location": "Japan",
            "seller": "facerecords",
            "seller_feedback": "99.8% positive",
            "ended": "Sold Aug 26, 2026",
            "image_url": "https://example.com/item.jpg",
        }
    ]


def write_payload(
    path: Path,
    payload: object,
) -> None:
    """Write one JSON payload."""
    path.write_text(
        json.dumps(
            payload
        ),
        encoding="utf-8",
    )


def test_load_listings_accepts_top_level_array(
    tmp_path: Path,
) -> None:
    """Accept the simplest external-collector payload shape."""
    path = (
        tmp_path
        / "ebay.json"
    )

    write_payload(
        path,
        sample_payload(),
    )

    listings = load_listings(
        path
    )

    assert listings == [
        EbayListing(
            item_id="188586715117",
            url="https://www.ebay.com/itm/188586715117",
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


def test_load_listings_accepts_listings_wrapper(
    tmp_path: Path,
) -> None:
    """Accept a metadata-friendly object wrapper."""
    path = (
        tmp_path
        / "ebay.json"
    )

    write_payload(
        path,
        {
            "listings": sample_payload(),
        },
    )

    listings = load_listings(
        path
    )

    assert len(listings) == 1
    assert (
        listings[0].item_id
        == "188586715117"
    )


@pytest.mark.parametrize(
    "payload, message",
    [
        (
            [],
            "zero listings",
        ),
        (
            {},
            "must contain a 'listings' field",
        ),
        (
            {
                "listings": "wrong",
            },
            "must be a JSON array",
        ),
        (
            {
                "listings": [
                    {
                        "item_id": "",
                        "url": "https://www.ebay.com/itm/1",
                        "title": "Example",
                    }
                ],
            },
            "Listing 1",
        ),
    ],
)
def test_load_listings_rejects_invalid_payloads(
    tmp_path: Path,
    payload: object,
    message: str,
) -> None:
    """Reject inputs that cannot safely become parser records."""
    path = (
        tmp_path
        / "invalid.json"
    )

    write_payload(
        path,
        payload,
    )

    with pytest.raises(
        StructuredEbayImportError,
        match=message,
    ):
        load_listings(
            path
        )


def test_persist_listings_creates_normal_ebay_raw_page() -> None:
    """Persist adapter HTML using the established raw-page contract."""
    session = FakeSession()

    listings = [
        EbayListing(
            item_id="188586715117",
            url="https://www.ebay.com/itm/188586715117",
            title="Teresa Teng LP",
            price="$42.00",
            seller="facerecords",
        )
    ]

    job, raw_page = persist_listings(
        session=session,  # type: ignore[arg-type]
        listings=listings,
        source_url=(
            "collector://ebay/facerecords"
        ),
    )

    assert job.id == 1
    assert job.source == "manual"
    assert job.status == "finished"

    assert raw_page.id == 2
    assert raw_page.crawl_job_id == 1
    assert raw_page.source == "ebay"
    assert (
        raw_page.url
        == "collector://ebay/facerecords"
    )
    assert raw_page.http_status == 200
    assert raw_page.listing_count == 1
    assert (
        raw_page.sha256
        == sha256_text(
            raw_page.html
        )
    )

    parsed = parse_search(
        raw_page.html
    )

    assert len(parsed) == 1
    assert (
        parsed[0]["item_id"]
        == "188586715117"
    )
    assert (
        parsed[0]["title"]
        == "Teresa Teng LP"
    )
    assert (
        parsed[0]["seller"]
        == "facerecords"
    )

    assert session.flush_count == 2
    assert session.commit_count == 1


def test_persist_listings_rejects_empty_collection() -> None:
    """Never create successful empty external eBay crawl jobs."""
    session = FakeSession()

    with pytest.raises(
        StructuredEbayImportError,
        match="At least one eBay listing is required",
    ):
        persist_listings(
            session=session,  # type: ignore[arg-type]
            listings=[],
            source_url=(
                "collector://ebay/facerecords"
            ),
        )

    assert session.added == []
    assert session.commit_count == 0
