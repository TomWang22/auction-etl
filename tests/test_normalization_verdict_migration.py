"""Normalization and deterministic verdict migration tests."""

from __future__ import annotations

from pathlib import Path


UP = Path(
    "alembic/versions/c1f4e8b7a630_normalization_and_verdict_rules_up.sql"
)

DOWN = Path(
    "alembic/versions/c1f4e8b7a630_normalization_and_verdict_rules_down.sql"
)

REVISION = Path(
    "alembic/versions/c1f4e8b7a630_normalization_and_verdict_rules.py"
)


def test_revision_chain() -> None:
    """The migration follows the reference-audit revision."""
    source = REVISION.read_text(
        encoding="utf-8"
    )

    assert 'revision: str = "c1f4e8b7a630"' in source
    assert (
        'down_revision: str | None = '
        '"9e4b7c2a6d15"'
        in source
    )


def test_rule_and_audit_tables_exist() -> None:
    """The upgrade installs rules and immutable audit history."""
    source = UP.read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "CREATE TABLE system.deterministic_verdict_rule",
        "CREATE TABLE system.deterministic_verdict_rule_audit",
        "capture_verdict_rule_audit",
        "reject_verdict_rule_audit_mutation",
        "deterministic_verdict_rule_audit_immutable",
    )

    for fragment in required_fragments:
        assert fragment in source


def test_professional_seed_rules() -> None:
    """Seed rules use formal market terminology."""
    source = UP.read_text(
        encoding="utf-8"
    )

    required_terms = (
        "Reissue market visibility",
        "Reissue price convergence",
        "First-press price parity",
        "Reissue price crossover",
        "Persistent reissue displacement",
        "Market noise or insufficient sample",
        "High auction impact",
        "High collector significance",
    )

    for term in required_terms:
        assert term in source


def test_downgrade_only_removes_new_rule_objects() -> None:
    """Downgrade does not remove warehouse curation data."""
    source = DOWN.read_text(
        encoding="utf-8"
    )

    assert (
        "warehouse.pressing_component_expectation"
        not in source
    )
    assert (
        "warehouse.auction_component_observation"
        not in source
    )
