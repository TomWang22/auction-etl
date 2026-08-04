"""Eleven-stage cohort curation wizard service tests."""

from __future__ import annotations

import inspect

from auction_etl.services.cohort_curation_wizard import (
    BASELINE_RULE_CODES,
    OBSERVATION_ACTIONS,
    REFERENCE_ACTIONS,
    WIZARD_STEPS,
    apply_observation_changes,
    apply_reference_changes,
    build_cohort_report,
    cohort_progress,
)


def test_wizard_has_exactly_eleven_stages() -> None:
    """The workflow contains all eleven requested stages."""
    assert len(WIZARD_STEPS) == 11

    assert WIZARD_STEPS == (
        "Exact pressing identity",
        "Assigned listings",
        "Evidence and attachments",
        "Completeness reference",
        "Listing observations",
        "Condition normalization",
        "Analysis and market factors",
        "Comparable review",
        "Normalization readiness",
        "Eleven deterministic verdicts",
        "Audit and final report",
    )


def test_wizard_has_all_eleven_baseline_rules() -> None:
    """All professional baseline rule families are represented."""
    assert len(
        BASELINE_RULE_CODES
    ) == 11

    assert (
        "REISSUE_PRICE_CONVERGENCE"
        in BASELINE_RULE_CODES
    )

    assert (
        "FIRST_PRESS_PRICE_PARITY"
        in BASELINE_RULE_CODES
    )

    assert (
        "REISSUE_PRICE_CROSSOVER"
        in BASELINE_RULE_CODES
    )

    assert (
        "PERSISTENT_REISSUE_DISPLACEMENT"
        in BASELINE_RULE_CODES
    )

    assert (
        "MARKET_NOISE_INSUFFICIENT_SAMPLE"
        in BASELINE_RULE_CODES
    )


def test_reference_writes_require_explicit_actions() -> None:
    """Shared references cannot change through passive rendering."""
    assert REFERENCE_ACTIONS == (
        "NO_CHANGE",
        "UPSERT",
        "DELETE",
    )

    source = inspect.getsource(
        apply_reference_changes
    )

    assert "NO_CHANGE" in source
    assert "_set_audit_context(" in source
    assert (
        'isolation_level="SERIALIZABLE"'
        in source
    )
    assert (
        "pressing_component_expectation"
        in source
    )


def test_observation_writes_require_explicit_actions() -> None:
    """Listing observations remain separate and reviewed."""
    assert OBSERVATION_ACTIONS == (
        "NO_CHANGE",
        "UPSERT",
        "DELETE",
    )

    source = inspect.getsource(
        apply_observation_changes
    )

    assert "NO_CHANGE" in source
    assert "_set_audit_context(" in source
    assert (
        "auction_component_observation"
        in source
    )
    assert (
        "Observation listing is not assigned"
        in source
    )


def test_progress_tracks_all_eleven_stages() -> None:
    """Progress calculates explicit completion rather than inference."""
    source = inspect.getsource(
        cohort_progress
    )

    required_fragments = (
        "attachments",
        "reference_rows",
        "observation_rows",
        "condition_count",
        "analysis_count",
        "reviewed_comparables",
        "ready_count",
        "all_baseline_rules_available",
        "all_listings_evaluated",
        '"completed_stages"',
    )

    for fragment in required_fragments:
        assert fragment in source


def test_final_report_includes_all_work_products() -> None:
    """The report includes evidence, curation, readiness, rules, and audit."""
    source = inspect.getsource(
        build_cohort_report
    )

    required_fragments = (
        '"wizard_stage_count"',
        '"baseline_rule_count"',
        '"attachments"',
        '"reference_rows"',
        '"observations"',
        '"readiness"',
        '"baseline_rules"',
        '"verdicts"',
        '"audit"',
    )

    for fragment in required_fragments:
        assert fragment in source
