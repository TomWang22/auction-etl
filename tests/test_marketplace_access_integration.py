"""Regression tests for production marketplace classifier wiring."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

BUYEE = (
    ROOT
    / "scripts"
    / "verify_buyee_session.py"
)

EBAY = (
    ROOT
    / "scripts"
    / "crawl_ebay_sources.py"
)


def function_source(
    path: Path,
    function_name: str,
) -> str:
    """Return one function's source."""
    source = path.read_text(
        encoding="utf-8"
    )
    tree = ast.parse(
        source,
        filename=str(path),
    )

    function = next(
        (
            node
            for node in tree.body
            if isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name
            == function_name
        ),
        None,
    )

    assert function is not None

    return (
        ast.get_source_segment(
            source,
            function,
        )
        or ""
    )


def test_buyee_main_uses_canonical_page_classifier() -> None:
    """Buyee production verifier must classify rendered responses."""
    source = function_source(
        BUYEE,
        "main",
    )

    assert (
        "marketplace_page_result("
        in source
    )
    assert (
        "MarketplaceAccessState.ACCESS_BLOCKED"
        in source
    )
    assert (
        "response.status"
        in source
    )
    assert (
        "access_block_reason("
        not in source
    )


def test_buyee_preserves_access_block_exit_contract() -> None:
    """Canonical classification still uses verifier exit code 4."""
    source = BUYEE.read_text(
        encoding="utf-8"
    )

    assert (
        "ACCESS_BLOCKED_EXIT_CODE = 4"
        in source
    )
    assert (
        "return ACCESS_BLOCKED_EXIT_CODE"
        in source
    )


def test_ebay_crawler_uses_canonical_page_classifier() -> None:
    """eBay production crawl must classify its real navigation response."""
    source = EBAY.read_text(
        encoding="utf-8"
    )

    assert (
        "classify_ebay_page("
        in source
    )
    assert (
        "MarketplaceAccessState.ACCESS_BLOCKED"
        in source
    )
    assert (
        "MarketplaceAccessState.UNKNOWN_ERROR"
        in source
    )
    assert (
        "response.status"
        in source
    )


def test_ebay_403_is_not_accepted_from_brand_text() -> None:
    """Production code must not use the word eBay as health evidence."""
    source = EBAY.read_text(
        encoding="utf-8"
    )

    assert (
        "page_result = classify_ebay_page("
        in source
    )
