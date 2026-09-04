"""Regression coverage for seller-scoped structured eBay acquisition."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

import scripts.acquire_ebay_structured as acquire


CONFIG = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "ebay_sources.json"
)


def parsed_record(
    item_id: str,
    seller: str,
) -> dict[str, str]:
    """Return one parser-compatible test record."""

    return {
        "item_id": item_id,
        "url": (
            "https://www.ebay.com/itm/"
            + item_id
        ),
        "title": (
            "Listing "
            + item_id
        ),
        "seller": seller,
        "price": "$10.00",
        "ended": "Sold Sep 1, 2026",
    }


def build_with_records(
    monkeypatch: pytest.MonkeyPatch,
    records: list[dict[str, str]],
    *,
    expected_seller: str | None,
) -> dict[str, object]:
    """Build one payload while replacing only the HTML parser."""

    monkeypatch.setattr(
        acquire,
        "parse_search",
        lambda _html: records,
    )

    return acquire.build_payload_from_html(
        html="<html><body>fixture</body></html>",
        source_name="facerecords",
        requested_url=(
            "https://www.ebay.com/sch/i.html"
        ),
        final_url=(
            "https://www.ebay.com/sch/i.html"
        ),
        http_status=200,
        item_link_count=len(
            records
        ),
        expected_seller=expected_seller,
        collected_at_utc="2026-09-03T00:00:00Z",
    )


def test_production_config_restores_facerecords_scope() -> None:
    """Production external acquisition must be seller-scoped."""

    payload = json.loads(
        CONFIG.read_text(
            encoding="utf-8"
        )
    )

    enabled = [
        row
        for row in payload
        if (
            isinstance(
                row,
                dict,
            )
            and row.get(
                "enabled",
                True,
            )
            is not False
        )
    ]

    assert len(enabled) == 1

    source = enabled[0]

    assert source[
        "name"
    ] == "facerecords"

    assert source[
        "seller"
    ] == "facerecords"

    assert source[
        "acquisition_mode"
    ] == "external"

    query = parse_qs(
        urlsplit(
            source[
                "url"
            ]
        ).query
    )

    assert query[
        "_ssn"
    ] == [
        "facerecords"
    ]

    assert query[
        "LH_Sold"
    ] == ["1"]

    assert query[
        "LH_Complete"
    ] == ["1"]

    assert query[
        "_sop"
    ] == ["13"]


def test_expected_seller_excludes_other_sellers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sponsored and broad-search sellers must not enter the handoff."""

    payload = build_with_records(
        monkeypatch,
        [
            parsed_record(
                "336753952812",
                "facerecords",
            ),
            parsed_record(
                "257714226344",
                "hunts4stuff",
            ),
        ],
        expected_seller="facerecords",
    )

    assert payload[
        "seller_filter"
    ] == "facerecords"

    assert payload[
        "listing_count"
    ] == 1

    listings = payload[
        "listings"
    ]

    assert isinstance(
        listings,
        list,
    )

    assert [
        row[
            "item_id"
        ]
        for row in listings
    ] == [
        "336753952812"
    ]


def test_expected_seller_matching_is_case_insensitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seller identity comparison should not depend on display casing."""

    payload = build_with_records(
        monkeypatch,
        [
            parsed_record(
                "336753952833",
                "FaceRecords",
            ),
        ],
        expected_seller="facerecords",
    )

    assert payload[
        "listing_count"
    ] == 1


def test_expected_seller_zero_match_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A seller-scoped run must never silently import another seller."""

    with pytest.raises(
        acquire.EbayAcquisitionError,
        match="expected seller",
    ):
        build_with_records(
            monkeypatch,
            [
                parsed_record(
                    "257714226344",
                    "hunts4stuff",
                ),
            ],
            expected_seller="facerecords",
        )


def test_unscoped_call_preserves_existing_parser_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing callers remain compatible when no seller is supplied."""

    payload = build_with_records(
        monkeypatch,
        [
            parsed_record(
                "336753952812",
                "facerecords",
            ),
            parsed_record(
                "257714226344",
                "hunts4stuff",
            ),
        ],
        expected_seller=None,
    )

    assert payload[
        "listing_count"
    ] == 2

    assert (
        "seller_filter"
        not in payload
    )


def test_production_config_uses_minimal_seller_search_url() -> None:
    """The producer URL must omit the broken broad-search modifiers."""

    payload = json.loads(
        CONFIG.read_text(
            encoding="utf-8"
        )
    )

    enabled = [
        row
        for row in payload
        if (
            isinstance(row, dict)
            and row.get("enabled", True) is not False
        )
    ]

    assert len(enabled) == 1

    source = enabled[0]

    parsed = urlsplit(
        str(
            source["url"]
        )
    )

    query = parse_qs(
        parsed.query,
        keep_blank_values=True,
    )

    assert parsed.path == "/sch/i.html"
    assert query["_nkw"] == ["teresa teng"]
    assert query["_ssn"] == ["facerecords"]
    assert query["LH_Complete"] == ["1"]
    assert query["LH_Sold"] == ["1"]
    assert query["_sop"] == ["13"]

    for forbidden_key in (
        "_sacat",
        "_from",
        "rt",
        "_ipg",
    ):
        assert forbidden_key not in query
