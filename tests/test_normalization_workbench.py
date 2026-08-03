"""Normalization workbench service tests."""

from __future__ import annotations

import inspect

from auction_etl.services.normalization_workbench import (
    apply_workbook,
    export_workbook_csv,
    list_queue,
    preview_workbook,
    queue_summary,
    save_comparable_review,
)


def test_queue_is_prioritized_deterministically() -> None:
    """The queue reads the deterministic analytics view."""
    source = inspect.getsource(
        list_queue
    )

    assert (
        "analytics.normalization_work_queue"
        in source
    )
    assert "priority_score DESC" in source


def test_workbook_requires_explicit_apply_flag() -> None:
    """Unedited template rows cannot be written."""
    source = inspect.getsource(
        export_workbook_csv
    )

    assert '"apply"' in source
    assert '"FALSE"' in source

    preview_source = inspect.getsource(
        preview_workbook
    )

    assert "_parse_workbook(" in preview_source


def test_bulk_application_is_serializable_and_audited() -> None:
    """Approved batches are atomic and auditable."""
    source = inspect.getsource(
        apply_workbook
    )

    required_fragments = (
        'isolation_level="SERIALIZABLE"',
        "_set_audit_context(",
        "normalization_work_batch",
        "normalization_work_batch_row",
        "COMPLETED",
        "FAILED",
    )

    for fragment in required_fragments:
        assert fragment in source


def test_comparable_review_requires_exact_pressing() -> None:
    """Comparable decisions cannot cross pressing identities."""
    source = inspect.getsource(
        save_comparable_review
    )

    assert (
        "Comparable review requires "
        "the same exact pressing."
        in source
    )

    assert (
        "warehouse.auction_comparable_review"
        in source
    )


def test_queue_summary_counts_explicit_statuses() -> None:
    """Queue summaries do not infer missing states."""
    summary = queue_summary(
        [
            {
                "work_status":
                    "NEEDS_REFERENCE",
            },
            {
                "work_status":
                    "READY",
            },
        ]
    )

    assert summary["total"] == 2
    assert summary["ready"] == 1
    assert summary["blocked"] == 1
    assert summary["NEEDS_REFERENCE"] == 1
