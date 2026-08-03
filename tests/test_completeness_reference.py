"""Tests for completeness-reference separation."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from auction_etl.services.completeness_reference import (
    normalize_listing_observation_rows,
    normalize_pressing_reference_rows,
    save_listing_observation_rows,
    save_pressing_reference_rows,
)


ACTIVE_CODES = (
    "OBI",
    "INSERT",
    "POSTER",
)


def reference_row(
    code: str,
    state: str,
) -> dict[str, object]:
    """Build one verified reference row."""
    return {
        "component_code": code,
        "variant_key": "",
        "variant_label": None,
        "expectation_state": state,
        "expected_quantity": 1,
        "evidence_source": "PRESSING_GUIDE",
        "confidence": "0.95",
        "notes": None,
    }


def test_verified_reference_requires_every_component() -> None:
    """A partial component list cannot define completeness."""
    with pytest.raises(
        ValueError,
        match="Every active component",
    ):
        normalize_pressing_reference_rows(
            [
                reference_row(
                    "OBI",
                    "REQUIRED",
                )
            ],
            ACTIVE_CODES,
        )


def test_verified_reference_rejects_unknown() -> None:
    """Unknown rows cannot enter a verified reference."""
    rows = [
        reference_row(
            "OBI",
            "REQUIRED",
        ),
        reference_row(
            "INSERT",
            "UNKNOWN",
        ),
        reference_row(
            "POSTER",
            "NOT_INCLUDED",
        ),
    ]

    with pytest.raises(
        ValueError,
        match="REQUIRED, OPTIONAL, or NOT_INCLUDED",
    ):
        normalize_pressing_reference_rows(
            rows,
            ACTIVE_CODES,
        )


def test_verified_reference_accepts_complete_profile() -> None:
    """Required, optional, and excluded rows form a profile."""
    rows = [
        reference_row(
            "OBI",
            "REQUIRED",
        ),
        reference_row(
            "INSERT",
            "OPTIONAL",
        ),
        reference_row(
            "POSTER",
            "NOT_INCLUDED",
        ),
    ]

    normalized = (
        normalize_pressing_reference_rows(
            rows,
            ACTIVE_CODES,
        )
    )

    assert len(normalized) == 3
    assert {
        row["expectation_state"]
        for row in normalized
    } == {
        "REQUIRED",
        "OPTIONAL",
        "NOT_INCLUDED",
    }


def test_observation_defaults_present_quantity() -> None:
    """Explicit presence defaults to quantity one."""
    rows = [
        {
            "component_code": "OBI",
            "observation_state": "PRESENT",
            "evidence_source": "LISTING_TITLE",
            "confidence": "0.99",
        }
    ]

    normalized = (
        normalize_listing_observation_rows(
            rows,
            ACTIVE_CODES,
        )
    )

    assert normalized[0][
        "observed_quantity"
    ] == 1


def test_reference_writer_cannot_delete_observations() -> None:
    """Pressing-reference saves stay in their own scope."""
    source = inspect.getsource(
        save_pressing_reference_rows
    )

    assert (
        "pressing_component_expectation"
        in source
    )
    assert (
        "auction_component_observation"
        not in source
    )


def test_observation_writer_cannot_delete_reference() -> None:
    """Listing saves stay in their own scope."""
    source = inspect.getsource(
        save_listing_observation_rows
    )

    assert (
        "auction_component_observation"
        in source
    )
    assert (
        "pressing_component_expectation"
        not in source
    )


def test_editor_exposes_two_separate_workflows() -> None:
    """The UI labels both persistence scopes clearly."""
    source = Path(
        "app/collector_analytics_editor.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "Pressing completeness reference"
        in source
    )
    assert (
        "This listing's observations"
        in source
    )
    assert (
        "Save verified pressing reference"
        in source
    )
    assert (
        "Save this listing's observations"
        in source
    )
