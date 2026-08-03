"""Add normalization readiness and deterministic verdict rules.

Revision ID: c1f4e8b7a630
Revises: 9e4b7c2a6d15
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from alembic import op


revision: str = "c1f4e8b7a630"
down_revision: str | None = "9e4b7c2a6d15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _sql(filename: str) -> str:
    """Load SQL adjacent to this migration."""
    return (
        Path(__file__)
        .with_name(filename)
        .read_text(encoding="utf-8")
    )


def upgrade() -> None:
    """Install audited deterministic verdict rules."""
    op.get_bind().exec_driver_sql(
        _sql(
            "c1f4e8b7a630_normalization_and_verdict_rules_up.sql"
        )
    )


def downgrade() -> None:
    """Remove deterministic verdict-rule objects."""
    op.get_bind().exec_driver_sql(
        _sql(
            "c1f4e8b7a630_normalization_and_verdict_rules_down.sql"
        )
    )
