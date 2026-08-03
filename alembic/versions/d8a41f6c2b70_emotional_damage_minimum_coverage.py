"""Require minimum Emotional Damage coverage.

Revision ID: d8a41f6c2b70
Revises: c4f8a2d7e901
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "d8a41f6c2b70"
down_revision = "c4f8a2d7e901"
branch_labels = None
depends_on = None

_REVISION_DIRECTORY = Path(__file__).resolve().parent


def _execute_sql(filename: str) -> None:
    """Execute one versioned SQL artifact."""
    sql = (
        _REVISION_DIRECTORY
        / filename
    ).read_text(
        encoding="utf-8"
    )

    op.get_bind().exec_driver_sql(sql)


def upgrade() -> None:
    """Require at least 50 percent damage coverage."""
    _execute_sql(
        "d8a41f6c2b70_"
        "emotional_damage_minimum_coverage_up.sql"
    )


def downgrade() -> None:
    """Restore score-only incident classification."""
    _execute_sql(
        "d8a41f6c2b70_"
        "emotional_damage_minimum_coverage_down.sql"
    )
