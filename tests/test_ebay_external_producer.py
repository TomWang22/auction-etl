"""Regression coverage for the external eBay handoff producer."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from auction_etl.browser.defaults import (
    CHANNEL,
    COLOR_SCHEME,
    LOCALE,
    TIMEZONE,
    USER_AGENT,
    VIEWPORT,
)
from scripts.acquire_ebay_structured import (
    persistent_profile_context_options,
)

from scripts.acquire_ebay_structured import (
    is_ebay_generic_error_page,
)

from scripts.produce_ebay_external_handoff import (
    ExternalProducerError,
    has_next_page,
    load_source,
    page_url,
    profile_directory,
)


def write_config(
    path: Path,
    *,
    seller: str = "facerecords",
    query_seller: str = "facerecords",
    mode: str = "external",
) -> None:
    """Write one minimal external source configuration."""

    path.write_text(
        json.dumps(
            [
                {
                    "name": "facerecords",
                    "seller": seller,
                    "url": (
                        "https://www.ebay.com/sch/i.html"
                        "?_nkw=teresa+teng"
                        f"&_ssn={query_seller}"
                        "&LH_Complete=1"
                        "&LH_Sold=1"
                        "&_sop=13"
                    ),
                    "enabled": True,
                    "max_pages": 25,
                    "profile": "facerecords",
                    "wait_seconds": 4.0,
                    "min_items": 1,
                    "acquisition_mode": mode,
                }
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_load_source_accepts_exact_seller_scope(
    tmp_path: Path,
) -> None:
    """A valid producer source must bind seller and query identity."""

    config = (
        tmp_path
        / "ebay.json"
    )

    write_config(
        config
    )

    source = load_source(
        config
    )

    assert source.name == "facerecords"
    assert source.seller == "facerecords"
    assert source.profile == "facerecords"
    assert source.max_pages == 25


def test_load_source_rejects_missing_seller_scope(
    tmp_path: Path,
) -> None:
    """An empty acquisition scope must fail validation."""

    config = (
        tmp_path
        / "ebay.json"
    )

    write_config(
        config,
        seller="",
        query_seller="",
    )

    with pytest.raises(
        ExternalProducerError,
        match="seller scope",
    ):
        load_source(
            config
        )



def test_load_source_rejects_mismatched_query_seller(
    tmp_path: Path,
) -> None:
    """Config metadata and actual eBay query must identify one seller."""

    config = (
        tmp_path
        / "ebay.json"
    )

    write_config(
        config,
        seller="facerecords",
        query_seller="other-seller",
    )

    with pytest.raises(
        ExternalProducerError,
        match="_ssn seller filter",
    ):
        load_source(
            config
        )


def test_load_source_requires_external_mode(
    tmp_path: Path,
) -> None:
    """The local handoff producer must not alter worker browser policy."""

    config = (
        tmp_path
        / "ebay.json"
    )

    write_config(
        config,
        mode="browser",
    )

    with pytest.raises(
        ExternalProducerError,
        match="acquisition_mode='external'",
    ):
        load_source(
            config
        )


def test_page_url_preserves_scope_and_adds_page_number() -> None:
    """Pagination must not drop seller or sold-result constraints."""

    source_url = (
        "https://www.ebay.com/sch/i.html"
        "?_nkw=teresa+teng"
        "&_ssn=facerecords"
        "&LH_Complete=1"
        "&LH_Sold=1"
        "&_sop=13"
    )

    second = page_url(
        source_url,
        2,
    )

    query = parse_qs(
        urlsplit(
            second
        ).query
    )

    assert query[
        "_ssn"
    ] == [
        "facerecords"
    ]

    assert query[
        "LH_Complete"
    ] == ["1"]

    assert query[
        "LH_Sold"
    ] == ["1"]

    assert query[
        "_sop"
    ] == ["13"]

    assert query[
        "_pgn"
    ] == ["2"]


def test_first_page_does_not_add_pagination_parameter() -> None:
    """Page one should retain the canonical configured URL semantics."""

    source_url = (
        "https://www.ebay.com/sch/i.html"
        "?_nkw=teresa+teng"
        "&_ssn=facerecords"
        "&LH_Complete=1"
        "&LH_Sold=1"
        "&_sop=13"
    )

    query = parse_qs(
        urlsplit(
            page_url(
                source_url,
                1,
            )
        ).query
    )

    assert "_pgn" not in query


def test_next_page_detection_requires_enabled_link() -> None:
    """Pagination should continue only when the captured page proves it."""

    assert (
        has_next_page(
            """
            <html>
              <a
                class="pagination__next"
                href="/sch/i.html?_pgn=2"
              >Next</a>
            </html>
            """
        )
        is True
    )

    assert (
        has_next_page(
            """
            <html>
              <a
                class="pagination__next"
                href="/sch/i.html?_pgn=2"
                aria-disabled="true"
              >Next</a>
            </html>
            """
        )
        is False
    )


def test_generic_ebay_error_page_is_rejected_before_item_wait() -> None:
    """The observed HTTP-200 eBay error page must not look like results."""

    assert is_ebay_generic_error_page(
        title="Error Page | eBay",
        body=(
            "SORRY Something went wrong on our end. "
            "Please go back and try again or go to eBay Homepage."
        ),
    )


def test_normal_ebay_results_are_not_generic_error_page() -> None:
    """A normal results page must remain eligible for item extraction."""

    assert not is_ebay_generic_error_page(
        title="Teresa Teng in Vinyl Records for sale | eBay",
        body="Teresa Teng sold vinyl records. 49 results.",
    )


def test_generic_error_check_precedes_item_link_wait() -> None:
    """HTTP-200 error classification must occur before result waiting."""

    root = Path(__file__).resolve().parents[1]

    source = (
        root
        / "scripts"
        / "acquire_ebay_structured.py"
    ).read_text(
        encoding="utf-8"
    )

    acquire_start = source.index(
        "def acquire_page("
    )

    acquire_source = source[
        acquire_start:
    ]

    error_check = acquire_source.index(
        "if is_ebay_generic_error_page("
    )

    item_wait = acquire_source.index(
        ".first.wait_for("
    )

    assert error_check < item_wait


def test_profile_acquisition_matches_managed_browser_defaults(
    tmp_path: Path,
) -> None:
    """Direct profile acquisition must preserve managed-browser identity."""

    options = persistent_profile_context_options(
        profile_dir=tmp_path,
        headless=False,
    )

    assert options[
        "user_data_dir"
    ] == str(
        tmp_path
    )

    assert options[
        "headless"
    ] is False

    assert options[
        "viewport"
    ] == VIEWPORT

    assert options[
        "locale"
    ] == LOCALE

    assert options[
        "timezone_id"
    ] == TIMEZONE

    assert options[
        "color_scheme"
    ] == COLOR_SCHEME

    if USER_AGENT is None:
        assert (
            "user_agent"
            not in options
        )
    else:
        assert options[
            "user_agent"
        ] == USER_AGENT

    if CHANNEL is None:
        assert (
            "channel"
            not in options
        )
    else:
        assert options[
            "channel"
        ] == CHANNEL



def test_load_source_accepts_public_all_sellers_scope(
    tmp_path: Path,
) -> None:
    """Public sold acquisition has no seller or persistent-profile requirement."""

    config = (
        tmp_path
        / "public-ebay.json"
    )

    config.write_text(
        json.dumps(
            [
                {
                    "name": "facerecords",
                    "seller": "all-sellers",
                    "url": (
                        "https://www.ebay.com/sch/i.html"
                        "?_nkw=teresa+teng"
                        "&LH_Complete=1"
                        "&LH_Sold=1"
                        "&_sop=13"
                    ),
                    "enabled": True,
                    "max_pages": 25,
                    "profile": "ebay-public",
                    "wait_seconds": 4.0,
                    "min_items": 1,
                    "acquisition_mode": "external",
                }
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    source = load_source(
        config
    )

    assert source.seller == "all-sellers"
    assert source.profile == "ebay-public"

    assert (
        profile_directory(
            source
        )
        is None
    )


def test_public_all_sellers_rejects_ssn(
    tmp_path: Path,
) -> None:
    """Public search cannot silently revert to a seller restriction."""

    config = (
        tmp_path
        / "bad-public-ebay.json"
    )

    config.write_text(
        json.dumps(
            [
                {
                    "name": "facerecords",
                    "seller": "all-sellers",
                    "url": (
                        "https://www.ebay.com/sch/i.html"
                        "?_nkw=teresa+teng"
                        "&_ssn=facerecords"
                        "&LH_Complete=1"
                        "&LH_Sold=1"
                        "&_sop=13"
                    ),
                    "enabled": True,
                    "max_pages": 25,
                    "profile": "ebay-public",
                    "wait_seconds": 4.0,
                    "min_items": 1,
                    "acquisition_mode": "external",
                }
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ExternalProducerError,
        match="must not contain an _ssn",
    ):
        load_source(
            config
        )
