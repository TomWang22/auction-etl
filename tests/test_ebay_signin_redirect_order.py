"""Regression tests for eBay sign-in redirect handling."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CRAWLER = ROOT / "scripts" / "crawl_ebay_sources.py"

CURRENT_URL = "current_url = page.url"
REDIRECT = 'if "signin.ebay." in current_url.casefold():'
CLASSIFIER = "page_result = classify_ebay_page("


def crawler_source() -> str:
    """Load syntactically valid crawler source."""
    source = CRAWLER.read_text(
        encoding="utf-8",
    )

    ast.parse(
        source,
        filename=str(CRAWLER),
    )

    return source


def test_signin_redirect_precedes_classifier_for_loaded_response() -> None:
    """Reject eBay sign-in redirects before generic page classification."""
    source = crawler_source()

    redirect_offset = source.index(
        REDIRECT,
    )

    block_start = source.rindex(
        CURRENT_URL,
        0,
        redirect_offset + 1,
    )

    classifier_offset = source.find(
        CLASSIFIER,
        block_start,
    )

    assert block_start < redirect_offset
    assert redirect_offset < classifier_offset


def test_exactly_one_signin_redirect_guard_exists() -> None:
    """Avoid duplicated or stale redirect handling."""
    source = crawler_source()

    assert source.count(
        REDIRECT
    ) == 1


def test_signin_redirect_preserves_runner_block_message() -> None:
    """Keep the error recognized by the refresh runner."""
    source = crawler_source()

    assert (
        '"eBay unexpectedly redirected the anonymous "'
        in source
    )
    assert (
        '"completed-search page to sign-in."'
        in source
    )
