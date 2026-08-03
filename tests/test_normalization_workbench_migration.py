"""Normalization workbench migration tests."""

from __future__ import annotations

from pathlib import Path


UP = Path("alembic/versions/e7b3c6d9a214_normalization_workbench_up.sql")
DOWN = Path("alembic/versions/e7b3c6d9a214_normalization_workbench_down.sql")
REVISION = Path("alembic/versions/e7b3c6d9a214_normalization_workbench.py")


def test_revision_chain() -> None:
    """The workbench follows deterministic verdict rules."""
    source = REVISION.read_text(
        encoding="utf-8"
    )

    assert 'revision: str = "e7b3c6d9a214"' in source
    assert (
        'down_revision: str | None = '
        '"c1f4e8b7a630"'
        in source
    )


def test_workbench_objects_are_installed() -> None:
    """The migration creates batches, reviews, audit, and queue."""
    source = UP.read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "system.normalization_work_batch",
        "system.normalization_work_batch_row",
        "system.normalization_work_audit_event",
        "warehouse.auction_comparable_review",
        "analytics.normalization_work_queue",
        "capture_normalization_work_audit",
        "reject_normalization_audit_mutation",
    )

    for fragment in required_fragments:
        assert fragment in source


def test_queue_has_professional_blockers() -> None:
    """The queue separates all normalization work classes."""
    source = UP.read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "PRESSING_ASSIGNMENT",
        "COMPLETENESS_REFERENCE",
        "REFERENCE_VERIFICATION",
        "CONDITION_NORMALIZATION",
        "COMPLETENESS_FACTOR",
        "PRICE_BASIS",
        "ELIGIBLE_COMPARABLES",
    )

    for fragment in required_fragments:
        assert fragment in source


def test_downgrade_preserves_existing_curation_tables() -> None:
    """Downgrade removes only this migration's objects."""
    source = DOWN.read_text(
        encoding="utf-8"
    )

    assert (
        "DROP TABLE IF EXISTS "
        "warehouse.auction_condition_normalization"
        not in source
    )

    assert (
        "DROP TABLE IF EXISTS "
        "warehouse.auction_analysis_input"
        not in source
    )
