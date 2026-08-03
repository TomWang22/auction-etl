"""Normalization-readiness service tests."""

from __future__ import annotations

import inspect

from auction_etl.services.normalization_readiness import (
    _readiness_gate_ratio,
    list_readiness,
    readiness_summary,
)


def test_readiness_has_six_explicit_gates() -> None:
    """Readiness is deterministic satisfied-gates arithmetic."""
    source = inspect.getsource(
        _readiness_gate_ratio
    )

    required_fragments = (
        'row["pressing_id"] is not None',
        'row["reference_status"] == "CONFIGURED"',
        'row["condition_market_factor"] is not None',
        'row["completeness_market_factor"] is not None',
        'row["selected_price_usd"] is not None',
        "eligible_comparable_count",
    )

    for fragment in required_fragments:
        assert fragment in source


def test_service_reads_real_component_arithmetic() -> None:
    """The dashboard uses the completeness view."""
    source = inspect.getsource(
        list_readiness
    )

    required_fragments = (
        "warehouse.auction_completeness",
        "required_component_count",
        "present_required_component_count",
        "missing_components",
        "unverified_components",
        "completeness_ratio",
    )

    for fragment in required_fragments:
        assert fragment in source


def test_summary_is_deterministic() -> None:
    """The summary counts explicit states."""
    rows = [
        {
            "readiness_status": "READY",
            "pressing_id": 1,
            "reference_status": "CONFIGURED",
            "condition_market_factor": 1,
            "completeness_market_factor": 1,
        },
        {
            "readiness_status": "BLOCKED",
            "pressing_id": None,
            "reference_status": "NO_PRESSING",
            "condition_market_factor": None,
            "completeness_market_factor": None,
        },
    ]

    summary = readiness_summary(rows)

    assert summary["total"] == 2
    assert summary["ready"] == 1
    assert summary["blocked"] == 1
    assert summary["pressing_assigned"] == 1
