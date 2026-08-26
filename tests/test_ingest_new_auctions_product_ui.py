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


def test_completed_refresh_keeps_final_progress_visible() -> None:
    """Completed refreshes keep a visible final progress result."""
    source = PAGE.read_text(
        encoding="utf-8",
    )

    assert 'if state != "completed":' not in source
    assert 'if state == "completed":' in source
    assert "progress = 100" not in source
    assert 'display_phase = "Completed"' in source
    assert "st.progress(" in source


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

def test_ingest_page_supports_both_durable_state_contracts() -> None:
    """Marketplace cards accept both durable refresh mappings."""
    value = PAGE.read_text(
        encoding="utf-8"
    )

    assert "def durable_source_states(" in value
    assert '"source_states"' in value
    assert '"marketplace_states"' in value
    assert 'if state == "skipped":' in value
    assert 'state = "unavailable"' in value


def test_completed_refresh_keeps_progress_bar_visible() -> None:
    """Completed refreshes retain a visible final progress result."""
    value = PAGE.read_text(
        encoding="utf-8"
    )

    assert 'if state != "completed":' not in value
    assert 'progress = 100' not in value
    assert 'display_phase = "Completed"' in value
    assert "st.progress(" in value


def test_missing_durable_source_state_is_not_fake_waiting() -> None:
    """Missing persisted state is distinguishable from genuine waiting."""
    value = PAGE.read_text(
        encoding="utf-8"
    )

    assert '"unknown"' in value
    assert 'return "Status unavailable"' in value
    assert '"waiting"' in value


def test_status_helpers_share_durable_source_state_normalization() -> None:
    """Warnings and success logic use the same durable state mapping."""
    value = PAGE.read_text(
        encoding="utf-8"
    )

    assert (
        value.count(
            "source_states = durable_source_states("
        )
        >= 4
    )
