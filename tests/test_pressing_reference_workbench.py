"""General pressing-reference workbench tests."""

from __future__ import annotations

import inspect
from decimal import Decimal

import pytest

from auction_etl.services.pressing_reference_workbench import (
    calculate_component_score,
    clone_reference,
    parse_reference_csv,
)


def test_parse_reference_csv_reads_detailed_rows() -> None:
    """CSV worksheets preserve component metadata."""
    payload = """component_code,expectation_state,expected_quantity,confidence,variant_key,evidence_source,notes
OBI,REQUIRED,1,0.99,PINK_OBI,PHYSICAL_COPY,Pink obi
POSTER,NOT_INCLUDED,0,0.95,,CATALOG_SCAN,No poster
"""

    rows = parse_reference_csv(
        payload
    )

    assert len(rows) == 2
    assert rows[0]["component_code"] == "OBI"
    assert rows[0]["variant_key"] == "PINK_OBI"
    assert rows[0]["confidence"] == Decimal("0.9900")
    assert rows[1]["expected_quantity"] == 0


def test_parse_reference_csv_rejects_duplicate_identity() -> None:
    """The same component variant cannot appear twice."""
    payload = """component_code,expectation_state,expected_quantity,confidence,variant_key
OBI,REQUIRED,1,0.99,
OBI,REQUIRED,1,0.99,
"""

    with pytest.raises(
        ValueError,
        match="Duplicate component/variant",
    ):
        parse_reference_csv(
            payload
        )


def test_component_score_is_quantity_based() -> None:
    """Completeness is calculated from required units."""
    rows = [
        {
            "component_code": "OBI",
            "variant_key": "",
            "expected_quantity": 1,
            "observation_state": "PRESENT",
            "observed_quantity": 1,
            "normalized_condition": "NM",
        },
        {
            "component_code": "POSTER",
            "variant_key": "",
            "expected_quantity": 1,
            "observation_state": "ABSENT",
            "observed_quantity": 0,
            "normalized_condition": None,
        },
        {
            "component_code": "INSERT",
            "variant_key": "",
            "expected_quantity": 2,
            "observation_state": "PRESENT",
            "observed_quantity": 1,
            "normalized_condition": "VG+",
        },
    ]

    result = calculate_component_score(
        rows,
        "INCOMPLETE",
    )

    assert result["required_units"] == 4.0
    assert result["present_units"] == 2.0
    assert result["absent_units"] == 1.0
    assert result["unverified_units"] == 1.0
    assert (
        result[
            "structural_completeness_percent"
        ]
        == 50.0
    )
    assert (
        result["verification_percent"]
        == 75.0
    )
    assert result["verdict"] == "INCOMPLETE"


def test_damage_adjustment_requires_full_condition_coverage() -> None:
    """Unknown component condition cannot be treated as perfect."""
    incomplete_grades = [
        {
            "component_code": "OBI",
            "expected_quantity": 1,
            "observation_state": "PRESENT",
            "observed_quantity": 1,
            "normalized_condition": "NM",
        },
        {
            "component_code": "INSERT",
            "expected_quantity": 1,
            "observation_state": "PRESENT",
            "observed_quantity": 1,
            "normalized_condition": None,
        },
    ]

    result = calculate_component_score(
        incomplete_grades,
        "COMPLETE",
    )

    assert (
        result[
            "structural_completeness_percent"
        ]
        == 100.0
    )
    assert (
        result[
            "condition_coverage_percent"
        ]
        == 50.0
    )
    assert (
        result[
            "damage_adjusted_percent"
        ]
        is None
    )
    assert result["verdict"] == "COMPLETE_UNGRADED"


def test_damage_adjustment_uses_exact_grade_tokens() -> None:
    """Canonical grades produce deterministic penalties."""
    rows = [
        {
            "component_code": "OBI",
            "expected_quantity": 1,
            "observation_state": "PRESENT",
            "observed_quantity": 1,
            "normalized_condition": "VG",
        },
        {
            "component_code": "INSERT",
            "expected_quantity": 1,
            "observation_state": "PRESENT",
            "observed_quantity": 1,
            "normalized_condition": "NM",
        },
    ]

    result = calculate_component_score(
        rows,
        "COMPLETE",
    )

    assert (
        result[
            "condition_coverage_percent"
        ]
        == 100.0
    )
    assert result["condition_percent"] == 79.5
    assert (
        result[
            "damage_adjusted_percent"
        ]
        == 79.5
    )
    assert (
        result[
            "damage_penalty_percent"
        ]
        == 20.5
    )
    assert result["verdict"] == "COMPLETE_WORN"


def test_factory_sealed_status_is_preserved() -> None:
    """The sealed exception remains a distinct verdict."""
    rows = [
        {
            "component_code": "OBI",
            "expected_quantity": 1,
            "observation_state": "PRESENT",
            "observed_quantity": 1,
            "normalized_condition": None,
        },
        {
            "component_code": "POSTER",
            "expected_quantity": 1,
            "observation_state": "NOT_VISIBLE",
            "observed_quantity": None,
            "normalized_condition": None,
        },
    ]

    result = calculate_component_score(
        rows,
        "FACTORY_SEALED_EXCEPTION",
    )

    assert (
        result["verdict"]
        == "FACTORY_SEALED_EXCEPTION"
    )
    assert (
        result[
            "structural_completeness_percent"
        ]
        == 50.0
    )
    assert result["unverified_units"] == 1.0


def test_clone_supports_safe_draft_and_confirmed_copy() -> None:
    """The service exposes both transfer safety modes."""
    source = inspect.getsource(
        clone_reference
    )

    assert '"DRAFT"' in source
    assert '"VERIFIED_COPY"' in source
    assert "overwrite" in source
    assert "source_pressing_id == target_pressing_id" in source
    assert "_draft_rows" in source
    assert "save_reference_rows" in source


def test_score_service_does_not_use_ai() -> None:
    """Component scoring is arithmetic and exact-token based."""
    source = inspect.getsource(
        calculate_component_score
    ).lower()

    forbidden_fragments = (
        "openai",
        "chatgpt",
        "language model",
        "llm",
        "embedding",
        "prompt",
    )

    for fragment in forbidden_fragments:
        assert fragment not in source
