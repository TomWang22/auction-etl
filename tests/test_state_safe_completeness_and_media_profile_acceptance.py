"""Structural tests for browser acceptance."""

from __future__ import annotations

from pathlib import Path


SCRIPT = Path(
    "scripts/accept_state_safe_completeness_and_profiles.py"
)


def test_acceptance_covers_both_pages_without_apply() -> None:
    """Both workflows render and persistence remains untouched."""
    source = SCRIPT.read_text(
        encoding="utf-8"
    )

    required = (
        "Listing Completeness Review",
        "Media Profile Administration",
        "Assigned auction listing",
        "Preview media-profile changes",
        "persistence_controls_clicked",
        "database_writes",
    )

    for fragment in required:
        assert fragment in source

    assert (
        "Apply reviewed media profile"
        not in source
    )

    assert (
        ".click("
        not in source
    )
