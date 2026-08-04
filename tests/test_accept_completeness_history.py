"""Tests for completeness-history browser acceptance."""

from pathlib import Path


SCRIPT = Path(
    "scripts/accept_completeness_history.py"
)


def test_acceptance_uses_proven_root_navigator() -> None:
    """The history acceptance starts from the Streamlit root."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    required = (
        "accept_state_safe_completeness_and_profiles.py",
        "_wait_for_root",
        "open_sidebar_page",
        "Completeness Snapshot History",
        "Assigned auction listing",
        "Chronological change timeline",
        "Immutable snapshot ledger",
        "persistence_controls_clicked",
        "database_writes",
    )

    for fragment in required:
        assert fragment in source


def test_acceptance_never_clicks_persistence_controls() -> None:
    """The browser command performs navigation only."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    forbidden = (
        "Apply reviewed",
        "Save changed",
        "Register attachment",
    )

    for fragment in forbidden:
        assert fragment not in source
