"""Pressing completeness-reference service tests."""

from __future__ import annotations

import inspect
from decimal import Decimal

import pytest

from auction_etl.services.pressing_reference_admin import list_pressings
from auction_etl.services.pressing_reference_admin import (
    normalize_reference_rows,
    save_reference_rows,
)


ACTIVE_CODES = (
    "OBI",
    "INSERT",
    "POSTER",
)


def _complete_rows() -> list[dict[str, object]]:
    """Return one valid reference fixture."""
    return [
        {
            "component_code": "OBI",
            "variant_key": "PINK",
            "variant_label": "Pink obi",
            "expectation_state": "REQUIRED",
            "expected_quantity": 1,
            "evidence_source": "PHYSICAL_COPY",
            "confidence": "0.99",
            "notes": "Verified against complete copy.",
        },
        {
            "component_code": "INSERT",
            "variant_key": "",
            "variant_label": "",
            "expectation_state": "REQUIRED",
            "expected_quantity": 1,
            "evidence_source": "CATALOG_SCAN",
            "confidence": "0.95",
            "notes": "",
        },
        {
            "component_code": "POSTER",
            "variant_key": "",
            "variant_label": "",
            "expectation_state": "NOT_INCLUDED",
            "expected_quantity": 99,
            "evidence_source": "CATALOG_SCAN",
            "confidence": "0.95",
            "notes": "",
        },
    ]


def test_normalize_reference_rows_accepts_full_reference() -> None:
    """Every active component can be classified precisely."""
    result = normalize_reference_rows(
        _complete_rows(),
        ACTIVE_CODES,
    )

    assert len(result) == 3
    assert result[0]["component_code"] == "OBI"
    assert result[0]["variant_key"] == "PINK"
    assert result[0]["confidence"] == Decimal("0.9900")

    poster = next(
        row
        for row in result
        if row["component_code"] == "POSTER"
    )

    assert poster["expectation_state"] == "NOT_INCLUDED"
    assert poster["expected_quantity"] == 0


def test_normalize_reference_requires_every_component() -> None:
    """Unclassified components keep the reference incomplete."""
    with pytest.raises(
        ValueError,
        match="Missing: POSTER",
    ):
        normalize_reference_rows(
            _complete_rows()[:2],
            ACTIVE_CODES,
        )


def test_normalize_reference_rejects_duplicate_variant() -> None:
    """One component variant cannot be defined twice."""
    rows = _complete_rows()

    rows.append(
        dict(rows[0])
    )

    with pytest.raises(
        ValueError,
        match="Duplicate component/variant",
    ):
        normalize_reference_rows(
            rows,
            ACTIVE_CODES,
        )


def test_normalize_reference_requires_evidence() -> None:
    """Reviewed claims require a reference source."""
    rows = _complete_rows()

    rows[0]["evidence_source"] = ""

    with pytest.raises(
        ValueError,
        match="requires an evidence source",
    ):
        normalize_reference_rows(
            rows,
            ACTIVE_CODES,
        )


def test_normalize_reference_requires_required_component() -> None:
    """A reference without required contents is invalid."""
    rows = _complete_rows()

    for row in rows:
        row["expectation_state"] = "NOT_INCLUDED"

    with pytest.raises(
        ValueError,
        match="At least one component",
    ):
        normalize_reference_rows(
            rows,
            ACTIVE_CODES,
        )


def test_reference_save_is_atomic_and_pressing_scoped() -> None:
    """Saving replaces only one pressing's shared reference."""
    source = inspect.getsource(
        save_reference_rows
    )

    assert "SERIALIZABLE" in source
    assert "pressing_identity" in source
    assert "pressing_component_expectation" in source
    assert "DELETE FROM" in source
    assert "INSERT INTO" in source
    assert "auction_component_observation" not in source
    assert "auction_pressing_assignment" not in source


def test_list_pressings_types_nullable_search_parameter() -> None:
    """PostgreSQL can type None-valued search parameters."""
    source = inspect.getsource(
        list_pressings
    )

    assert (
        "CAST(:search AS text) IS NULL"
        in source
    )
    assert (
        "ILIKE '%' || CAST(:search AS text) || '%'"
        in source
    )
    assert ":search IS NULL" not in source
    assert "ILIKE '%' || :search || '%'" not in source
