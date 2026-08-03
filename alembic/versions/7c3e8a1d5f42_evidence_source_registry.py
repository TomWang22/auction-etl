"""Add reusable evidence-source registry.

Revision ID: 7c3e8a1d5f42
Revises: f2a7c9e4b610
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from alembic import op


revision: str = "7c3e8a1d5f42"
down_revision: str | None = "f2a7c9e4b610"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _sql(filename: str) -> str:
    """Load migration SQL adjacent to this revision."""
    return (
        Path(__file__)
        .with_name(filename)
        .read_text(encoding="utf-8")
    )


def upgrade() -> None:
    """Install the evidence-source registry."""
    op.get_bind().exec_driver_sql(
        _sql(
            "7c3e8a1d5f42_evidence_source_registry_up.sql"
        )
    )


def downgrade() -> None:
    """Remove the evidence-source registry."""
    op.get_bind().exec_driver_sql(
        _sql(
            "7c3e8a1d5f42_evidence_source_registry_down.sql"
        )
    )
