"""Tests for collector curation validation."""

from __future__ import annotations

from decimal import Decimal

import pytest

from auction_etl.services.collector_curation import (
    BIDDER_STATES,
    EXPECTATION_STATES,
    MATCH_BASES,
    OBSERVATION_STATES,
    PRESSING_GENERATIONS,
    PRICE_BASES,
    normalize_bidder_count,
    normalize_component_rows,
    normalize_identity_key,
    optional_decimal,
    optional_integer,
    validated_choice,
)


def test_contract_choices_match_database() -> None:
    assert PRESSING_GENERATIONS == (
        "FIRST_PRESS",
        "EARLY_PRESS",
        "STANDARD",
        "PROMO",
        "REISSUE",
        "MODERN_REPRESS",
        "UNKNOWN",
    )

    assert MATCH_BASES == (
        "MANUAL",
        "CATALOG_EXACT",
        "MATRIX_EXACT",
        "TITLE_RULE",
        "MODEL",
        "IMPORT",
        "UNKNOWN",
    )

    assert EXPECTATION_STATES == (
        "REQUIRED",
        "OPTIONAL",
        "NOT_INCLUDED",
        "UNKNOWN",
    )

    assert OBSERVATION_STATES == (
        "PRESENT",
        "ABSENT",
        "UNKNOWN",
        "NOT_VISIBLE",
        "NOT_APPLICABLE",
    )

    assert BIDDER_STATES == (
        "OBSERVED",
        "MANUAL",
        "NOT_EXPOSED",
        "UNAVAILABLE",
        "ESTIMATED",
    )

    assert PRICE_BASES == (
        "HAMMER",
        "GROSS",
        "LANDED",
    )


def test_normalize_identity_key() -> None:
    assert normalize_identity_key(
        "  TERESA   TENG  愛人  "
    ) == "teresa teng 愛人"


def test_optional_integer_range() -> None:
    assert optional_integer(
        "12",
        minimum=1,
    ) == 12

    with pytest.raises(
        ValueError,
        match="at least 1",
    ):
        optional_integer(
            0,
            minimum=1,
        )


def test_optional_decimal_accepts_zero_score() -> None:
    assert optional_decimal(
        0,
        minimum=Decimal("0"),
        maximum=Decimal("20"),
    ) == Decimal("0")


def test_optional_decimal_rejects_zero_factor() -> None:
    with pytest.raises(
        ValueError,
        match="greater than 0",
    ):
        optional_decimal(
            0,
            minimum=Decimal("0"),
            minimum_exclusive=True,
        )


def test_validated_choice_normalizes_case() -> None:
    assert validated_choice(
        "gross",
        PRICE_BASES,
        "Price basis",
        "GROSS",
    ) == "GROSS"


def test_buyee_not_exposed_forces_null_count() -> None:
    assert normalize_bidder_count(
        "NOT_EXPOSED",
        27,
    ) == (
        "NOT_EXPOSED",
        None,
    )


def test_unavailable_forces_null_count() -> None:
    assert normalize_bidder_count(
        "UNAVAILABLE",
        4,
    ) == (
        "UNAVAILABLE",
        None,
    )


def test_manual_bidder_state_requires_count() -> None:
    with pytest.raises(
        ValueError,
        match="count is required",
    ):
        normalize_bidder_count(
            "MANUAL",
            None,
        )


def test_observed_bidder_count_is_preserved() -> None:
    assert normalize_bidder_count(
        "OBSERVED",
        6,
    ) == (
        "OBSERVED",
        6,
    )


def test_component_rows_preserve_unknown_and_not_visible() -> None:
    rows = normalize_component_rows(
        [
            {
                "component_code": "OBI",
                "expectation_state":
                    "REQUIRED",
                "expected_quantity": 1,
                "observation_state":
                    "NOT_VISIBLE",
                "observation_confidence":
                    "0.75",
            }
        ]
    )

    assert rows[0][
        "expectation_state"
    ] == "REQUIRED"

    assert rows[0][
        "observation_state"
    ] == "NOT_VISIBLE"

    assert rows[0][
        "observation_confidence"
    ] == Decimal("0.75")


def test_component_rows_reject_duplicate_variant() -> None:
    with pytest.raises(
        ValueError,
        match="Duplicate component identity",
    ):
        normalize_component_rows(
            [
                {
                    "component_code":
                        "OBI",
                    "variant_key":
                        "pink",
                },
                {
                    "component_code":
                        "OBI",
                    "variant_key":
                        "pink",
                },
            ]
        )


def test_component_confidence_range() -> None:
    with pytest.raises(
        ValueError,
        match="at most 1",
    ):
        normalize_component_rows(
            [
                {
                    "component_code":
                        "POSTER",
                    "expectation_confidence":
                        "1.1",
                }
            ]
        )
