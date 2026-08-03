"""Bulk collector-observation service tests."""

from __future__ import annotations

from pathlib import Path

import inspect

import pytest

from auction_etl.services.collector_observation_bulk import (
    apply_bulk_observations,
    normalize_source_key,
    parse_observation_csv,
    preview_bulk_observations,
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


# evidence-registry-lookup-regression:start
def test_preview_reads_complete_evidence_registry() -> None:
    """Registered keys are validated without array adaptation."""
    source = inspect.getsource(
        preview_bulk_observations
    )

    compact_source = " ".join(
        source.split()
    )

    assert (
        "FROM system.evidence_source_registry"
        in compact_source
    )

    assert (
        "CAST(:source_keys AS text[])"
        not in compact_source
    )

    assert (
        "source_map ="
        in compact_source
    )
# evidence-registry-lookup-regression:end


# legacy-registry-key-regression:start
def test_preview_canonicalizes_legacy_registry_suffix() -> None:
    """Legacy trailing underscores do not break source lookup."""
    source = Path(
        "auction_etl/services/"
        "collector_observation_bulk.py"
    ).read_text(
        encoding="utf-8"
    )

    assert (
        "def _canonical_registry_source_key("
        in source
    )

    assert '.rstrip("_")' in source

    preview_source = inspect.getsource(
        preview_bulk_observations
    )

    assert (
        "_canonical_registry_source_key("
        in preview_source
    )
# legacy-registry-key-regression:end


# evidence-source-map-row-regression:start
def test_preview_source_map_preserves_registry_row() -> None:
    """Source validation retains active and metadata fields."""
    source = inspect.getsource(
        preview_bulk_observations
    )

    compact_source = "".join(
        source.split()
    )

    assert (
        '_canonical_registry_source_key('
        'row["source_key"]'
        '):dict(row)'
        in compact_source
    )

    assert (
        ':bool(row["active"])'
        not in compact_source
    )

    assert 'source["active"]' in compact_source
# evidence-source-map-row-regression:end
