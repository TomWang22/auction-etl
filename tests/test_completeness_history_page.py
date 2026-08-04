"""Tests for completeness-history Streamlit pages."""

from __future__ import annotations

import ast
from pathlib import Path


HISTORY_PAGE = Path(
    "app/pages/12_Completeness_History.py"
)

LISTING_PAGE = Path(
    "app/pages/10_Listing_Completeness_Review.py"
)


def test_history_page_is_read_only() -> None:
    """The timeline page never mutates PostgreSQL."""
    source = HISTORY_PAGE.read_text(
        encoding="utf-8"
    )

    required = (
        "Completeness Snapshot History",
        "Assigned auction listing",
        "Chronological change timeline",
        "Immutable snapshot ledger",
        "Only REQUIRED",
    )

    for fragment in required:
        assert fragment in source

    forbidden = (
        ".button(",
        "--apply",
        "INSERT INTO",
        "UPDATE ",
        "DELETE FROM",
    )

    for fragment in forbidden:
        assert fragment not in source


def test_listing_page_links_to_history() -> None:
    """Listing Completeness Review exposes the history workflow."""
    source = LISTING_PAGE.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(
        source
    )

    assert (
        "pages/12_Completeness_History.py"
        in source
    )

    page_link_calls = [
        node
        for node in ast.walk(
            tree
        )
        if isinstance(
            node,
            ast.Call,
        )
        and isinstance(
            node.func,
            ast.Attribute,
        )
        and node.func.attr == "page_link"
    ]

    assert page_link_calls
