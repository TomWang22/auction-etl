"""Regression tests for deployed marketplace acquisition fixes."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]


def test_buyee_public_module_imports_and_disabled_config_skips() -> None:
    """Disabled public Buyee configuration must import and yield no sources."""
    from scripts import crawl_buyee_public_sources as crawler

    sources = crawler.load_sources(
        ROOT
        / "config"
        / "buyee_sources.json"
    )

    assert sources == []


def test_buyee_one_off_search_url_is_valid() -> None:
    """The local Buyee URL builder must produce a completed-auction query."""
    from scripts import crawl_buyee_public_sources as crawler

    source = crawler.one_off_source(
        "Teresa Teng"
    )

    parsed = urlsplit(
        source.url
    )

    query = parse_qs(
        parsed.query
    )

    assert parsed.scheme == "https"
    assert parsed.hostname == "buyee.jp"
    assert parsed.path == "/item/search"
    assert query["query"] == [
        "Teresa Teng"
    ]
    assert query["closed"] == [
        "1"
    ]


def test_production_ebay_uses_anonymous_browser() -> None:
    """Production eBay must run through the anonymous browser path."""
    import json

    config = json.loads(
        (
            ROOT
            / "config"
            / "ebay_sources.json"
        ).read_text(
            encoding="utf-8"
        )
    )

    assert len(config) == 1

    source = config[0]

    assert source[
        "acquisition_mode"
    ] == "browser"

    assert source[
        "profile"
    ] == "ebay-public"

    assert source[
        "seller"
    ] == "all-sellers"
