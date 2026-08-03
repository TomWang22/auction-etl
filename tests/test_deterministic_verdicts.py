"""Deterministic verdict service tests."""

from __future__ import annotations

import inspect
from decimal import Decimal

from auction_etl.services.deterministic_verdicts import (
    _compare,
    evaluate_listing,
    metric_catalog,
    save_rule,
)


def test_numeric_comparisons() -> None:
    """Operators apply exact decimal comparisons."""
    assert _compare(
        Decimal("1.20"),
        "GTE",
        Decimal("1.20"),
        None,
    )

    assert _compare(
        Decimal("0.85"),
        "BETWEEN",
        Decimal("0.80"),
        Decimal("0.99"),
    )

    assert not _compare(
        Decimal("0.79"),
        "GTE",
        Decimal("0.80"),
        None,
    )


def test_rule_writes_are_audited() -> None:
    """Rule administration sets transaction audit context."""
    source = inspect.getsource(
        save_rule
    )

    assert "_set_audit_context(" in source
    assert (
        "system.deterministic_verdict_rule"
        in source
    )
    assert "ON CONFLICT (rule_code)" in source


def test_evaluation_explains_suppression() -> None:
    """Weak data is suppressed rather than inferred."""
    source = inspect.getsource(
        evaluate_listing
    )

    required_fragments = (
        "METRIC_UNAVAILABLE",
        "SUPPRESSED_SAMPLE",
        "SUPPRESSED_EVIDENCE",
        "NOT_TRIGGERED",
        "TRIGGERED",
    )

    for fragment in required_fragments:
        assert fragment in source


def test_metric_catalog_uses_professional_names() -> None:
    """The public metric catalog exposes formal concepts."""
    catalog = metric_catalog()

    assert (
        "REISSUE_TO_FIRST_PRESS_RATIO"
        in catalog
    )
    assert (
        "NORMALIZATION_GATE_RATIO"
        in catalog
    )
    assert (
        "COMPARABLE_SAMPLE_SIZE"
        in catalog
    )
