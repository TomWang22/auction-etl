"""Static product-contract tests for the marketplace refresh page."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = (
    ROOT
    / "app"
    / "pages"
    / "15_Ingest_New_Auctions.py"
)


def test_page_compiles_and_uses_product_copy() -> None:
    """The page exposes concise marketplace-refresh language."""

    source = PAGE.read_text(
        encoding="utf-8",
    )

    ast.parse(
        source,
        filename=str(
            PAGE
        ),
    )

    required = (
        "Refresh Marketplace Sales",
        "Refresh marketplace sales",
        "Retry marketplace refresh",
        "Refresh status",
        "Technical details",
        "Marketplace sales are up to date.",
        "eBay",
        "Buyee",
        "Gripsweat",
    )

    for text in required:
        assert text in source


def test_page_does_not_launch_another_app_or_browser() -> None:
    """Normal product interaction stays inside the existing app."""

    source = PAGE.read_text(
        encoding="utf-8",
    )

    forbidden = (
        "webbrowser",
        "subprocess.Popen",
        "streamlit run",
        "server.port",
        "open(",
    )

    for marker in forbidden:
        assert marker not in source


def test_internal_runner_copy_is_not_user_facing() -> None:
    """Implementation details are kept out of normal product copy."""

    source = PAGE.read_text(
        encoding="utf-8",
    )

    assert (
        "This control uses scripts/run_auction_refresh_on_demand.sh"
        not in source
    )

    assert (
        "It does not rerun the old release/finalization chain."
        not in source
    )

    assert "Live ingestion log" not in source
