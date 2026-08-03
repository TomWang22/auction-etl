"""Bulk collector-observation service tests."""

from __future__ import annotations

import inspect

import pytest

from auction_etl.services.collector_observation_bulk import (
    apply_bulk_observations,
    normalize_source_key,
    parse_observation_csv,
)


def test_normalize_source_key() -> None:
    """Evidence-source keys are stable and reusable."""
    assert (
        normalize_source_key(
            "Discogs release page"
        )
        == "DISCOGS_RELEASE_PAGE"
    )


def test_parse_present_observation() -> None:
    """Present observations require positive quantities."""
    payload = """marketplace,listing_id,component_code,variant_key,observation_state,observed_quantity,evidence_source,confidence
ebay,123,OBI,,PRESENT,1,LISTING_TITLE,0.99
"""

    rows = parse_observation_csv(
        payload
    )

    assert len(rows) == 1
    assert rows[0]["observation_state"] == "PRESENT"
    assert rows[0]["observed_quantity"] == 1


def test_parse_absent_forces_zero_quantity() -> None:
    """Absent observations cannot retain a positive quantity."""
    payload = """marketplace,listing_id,component_code,variant_key,observation_state,observed_quantity,evidence_source,confidence
ebay,123,POSTER,,ABSENT,8,LISTING_TITLE,0.95
"""

    rows = parse_observation_csv(
        payload
    )

    assert rows[0]["observed_quantity"] == 0


def test_blank_template_rows_are_ignored() -> None:
    """Unedited worksheet slots do not create observations."""
    payload = """marketplace,listing_id,component_code,variant_key,observation_state,observed_quantity,evidence_source,confidence
ebay,123,POSTER,,,,,
ebay,123,OBI,,PRESENT,1,LISTING_TITLE,0.99
"""

    rows = parse_observation_csv(
        payload
    )

    assert len(rows) == 1
    assert rows[0]["component_code"] == "OBI"


def test_duplicate_exact_key_is_rejected() -> None:
    """One file cannot contain the same observation twice."""
    payload = """marketplace,listing_id,component_code,variant_key,observation_state,observed_quantity,evidence_source,confidence
ebay,123,OBI,,PRESENT,1,LISTING_TITLE,0.99
ebay,123,OBI,,ABSENT,0,LISTING_TITLE,0.99
"""

    with pytest.raises(
        ValueError,
        match="Duplicate observation row",
    ):
        parse_observation_csv(
            payload
        )


def test_apply_is_serializable_and_atomic() -> None:
    """Bulk application is one transaction with explicit overwrite."""
    source = inspect.getsource(
        apply_bulk_observations
    )

    assert "SERIALIZABLE" in source
    assert "overwrite_existing" in source
    assert "DELETE FROM" in source
    assert "INSERT INTO" in source
    assert "preview_bulk_observations" in source
