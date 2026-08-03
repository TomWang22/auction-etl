"""Tests for the Emotional Damage coverage migration."""

from __future__ import annotations

import ast
from pathlib import Path


REVISION = "d8a41f6c2b70"
BASE_REVISION = "c4f8a2d7e901"

VERSION_DIRECTORY = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
)

MIGRATION_PATH = (
    VERSION_DIRECTORY
    / f"{REVISION}_"
    "emotional_damage_minimum_coverage.py"
)

UP_PATH = (
    VERSION_DIRECTORY
    / f"{REVISION}_"
    "emotional_damage_minimum_coverage_up.sql"
)

DOWN_PATH = (
    VERSION_DIRECTORY
    / f"{REVISION}_"
    "emotional_damage_minimum_coverage_down.sql"
)


def test_revision_metadata() -> None:
    """The migration extends the collector analytics head."""
    source = MIGRATION_PATH.read_text(
        encoding="utf-8"
    )

    tree = ast.parse(source)

    assignments = {
        node.targets[0].id:
            node.value.value
        for node in tree.body
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(
                node.targets[0],
                ast.Name,
            )
            and isinstance(
                node.value,
                ast.Constant,
            )
        )
    }

    assert assignments["revision"] == REVISION
    assert (
        assignments["down_revision"]
        == BASE_REVISION
    )


def test_upgrade_requires_half_coverage() -> None:
    """Low-coverage scores must remain unclassified."""
    sql = UP_PATH.read_text(
        encoding="utf-8"
    )

    assert (
        sql.count(
            "emotional_damage_coverage "
            "< 0.5::numeric"
        )
        == 1
    )

    assert (
        "THEN 'INSUFFICIENT_DATA'::text"
        in sql
    )

    assert (
        "CREATE OR REPLACE VIEW "
        "analytics.emotional_damage"
        in sql
    )


def test_downgrade_restores_score_only_logic() -> None:
    """Downgrade restores the original classification."""
    sql = DOWN_PATH.read_text(
        encoding="utf-8"
    )

    assert (
        "emotional_damage_coverage "
        "< 0.5::numeric"
        not in sql
    )

    assert (
        "WHEN emotional_damage_score IS NULL "
        "THEN 'INSUFFICIENT_DATA'::text"
        in " ".join(sql.split())
    )


def test_upgrade_preserves_incident_thresholds() -> None:
    """Existing severity thresholds remain unchanged."""
    sql = UP_PATH.read_text(
        encoding="utf-8"
    )

    expected = (
        ("90::numeric", "SKINWALKER_RANCH"),
        ("75::numeric", "SEV_0"),
        ("60::numeric", "BIDDER_IDENTITY_WAR"),
        ("40::numeric", "MAJOR_INCIDENT"),
        ("20::numeric", "ELEVATED"),
    )

    for threshold, classification in expected:
        assert threshold in sql
        assert classification in sql
