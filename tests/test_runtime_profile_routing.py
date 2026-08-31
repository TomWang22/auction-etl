"""Shared eBay authentication-profile routing regression tests."""

from __future__ import annotations

from urllib.parse import parse_qs
from urllib.parse import urlsplit

from auction_etl.services.artist_tracking import (
    _generated_ebay_source,
)


def test_generated_source_reuses_authenticated_template_profile(
    monkeypatch,
) -> None:
    """Generated artist searches share one authenticated browser profile."""

    monkeypatch.delenv(
        "AUCTION_EBAY_PROFILE_NAME",
        raising=False,
    )

    source = _generated_ebay_source(
        {
            "id":
                "momoe-yamaguchi",
            "name":
                "Momoe Yamaguchi",
            "query":
                "Momoe Yamaguchi",
        },
        {
            "name":
                "facerecords",
            "profile":
                "facerecords",
            "seller":
                "facerecords",
            "enabled":
                True,
            "max_pages":
                25,
        },
    )

    query = parse_qs(
        urlsplit(
            source[
                "url"
            ]
        ).query
    )

    assert (
        source[
            "profile"
        ]
        == "facerecords"
    )

    assert (
        source[
            "seller"
        ]
        == ""
    )

    assert query.get(
        "LH_Sold"
    ) == [
        "1",
    ]

    assert query.get(
        "LH_Complete"
    ) == [
        "1",
    ]

    assert query.get(
        "_sacat"
    ) == [
        "176985",
    ]

    assert "_ssn" not in query


def test_generated_source_honors_shared_profile_override(
    monkeypatch,
) -> None:
    """Deployment may explicitly select the shared eBay profile."""

    monkeypatch.setenv(
        "AUCTION_EBAY_PROFILE_NAME",
        "shared-ebay",
    )

    source = _generated_ebay_source(
        {
            "id":
                "artist",
            "name":
                "Artist",
            "query":
                "Artist",
        },
        {
            "profile":
                "facerecords",
            "seller":
                "",
        },
    )

    assert (
        source[
            "profile"
        ]
        == "shared-ebay"
    )
