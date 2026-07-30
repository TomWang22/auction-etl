"""Static contract tests for the latest-auction Streamlit page."""

from __future__ import annotations

from pathlib import Path


PAGE_PATH = Path(
    "app/pages/3_Latest_Auction_Refresh.py"
)


def test_latest_refresh_page_contains_required_controls() -> None:
    """The page should expose the complete reporting workflow."""
    source = PAGE_PATH.read_text(
        encoding="utf-8"
    )

    required_labels = (
        "Latest Auction Refresh",
        "Inspect recent ingestion",
        "Run Buyee, eBay, and Gripsweat",
        "Recent additions",
        "First-seen range",
        "Auction-ended range",
        "Media-type breakdown",
        "Report fields",
        "Download formatted CSV",
        "Allowed media classifications",
        "Manual and effective classification fields",
    )

    for label in required_labels:
        assert label in source


def test_refresh_requires_explicit_run_confirmation() -> None:
    """The complete refresh must retain an explicit confirmation."""
    source = PAGE_PATH.read_text(
        encoding="utf-8"
    )

    assert 'confirmation.strip().upper() == "RUN"' in source
    assert "disabled=not refresh_enabled" in source
