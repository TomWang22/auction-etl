"""Static product-contract tests for the marketplace refresh page."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(
    __file__
).resolve().parents[
    1
]

PAGE = (
    ROOT
    / "app"
    / "pages"
    / "15_Ingest_New_Auctions.py"
)


def test_page_compiles_and_uses_user_facing_refresh_copy() -> None:
    """Expose the normal refresh workflow without operational noise."""

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
        "Previous refresh",
        "Latest refresh",
        "Advanced technical details",
        "Run details",
        "Log output",
        "Duration",
        "Marketplace sales are up to date.",
        "eBay",
        "Buyee",
        "Gripsweat",
    )

    missing = [
        text
        for text in required
        if text not in source
    ]

    assert not missing, (
        "Missing refresh UX contracts: "
        + ", ".join(
            missing
        )
    )


def test_completed_refresh_does_not_need_a_redundant_progress_bar() -> None:
    """Keep completed state focused on outcome rather than 100% mechanics."""

    source = PAGE.read_text(
        encoding="utf-8",
    )

    assert (
        'if state != "completed":'
        in source
    )

    assert (
        '"Latest refresh"'
        in source
    )


def test_technical_output_is_explicitly_advanced_and_secondary() -> None:
    """Keep raw runner output available only for troubleshooting."""

    source = PAGE.read_text(
        encoding="utf-8",
    )

    assert (
        '"Advanced technical details"'
        in source
    )

    assert (
        '"Technical details"'
        not in source
    )

    assert (
        "line_count=80"
        in source
    )

    assert (
        '"Download full refresh log"'
        in source
    )

    assert (
        "Most users can ignore this section."
        in source
    )


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
    """Implementation details stay out of normal product copy."""

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

    assert (
        "Live ingestion log"
        not in source
    )
