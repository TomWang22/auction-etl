"""Evidence-source registry migration contracts."""

from __future__ import annotations

from pathlib import Path


UP = Path(
    "alembic/versions/7c3e8a1d5f42_evidence_source_registry_up.sql"
)

DOWN = Path(
    "alembic/versions/7c3e8a1d5f42_evidence_source_registry_down.sql"
)

REVISION = Path(
    "alembic/versions/7c3e8a1d5f42_evidence_source_registry.py"
)


def test_revision_chain() -> None:
    """The migration extends the current sealed revision."""
    source = REVISION.read_text(
        encoding="utf-8"
    )

    assert 'revision: str = "7c3e8a1d5f42"' in source
    assert (
        'down_revision: str | None = '
        '"f2a7c9e4b610"'
        in source
    )


def test_registry_constraints() -> None:
    """Registry keys and confidence values are constrained."""
    source = UP.read_text(
        encoding="utf-8"
    )

    assert (
        "CREATE TABLE system.evidence_source_registry"
        in source
    )
    assert "source_key varchar(80) PRIMARY KEY" in source
    assert "default_confidence >= 0" in source
    assert "default_confidence <= 1" in source
    assert "existing_sources AS" in source


def test_downgrade_removes_only_registry() -> None:
    """Downgrade does not touch curation observations."""
    source = DOWN.read_text(
        encoding="utf-8"
    )

    assert (
        "DROP TABLE IF EXISTS "
        "system.evidence_source_registry"
        in source
    )
    assert (
        "auction_component_observation"
        not in source
    )
