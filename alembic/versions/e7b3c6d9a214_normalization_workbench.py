"""Add the normalization workbench and audited bulk curation.

Revision ID: e7b3c6d9a214
Revises: c1f4e8b7a630
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from alembic import op


revision: str = "e7b3c6d9a214"
down_revision: str | None = "c1f4e8b7a630"
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
    """Install normalization workbench objects."""
    op.get_bind().exec_driver_sql(
        _sql(
            "e7b3c6d9a214_normalization_workbench_up.sql"
        )
    )


def downgrade() -> None:
    """Remove normalization workbench objects."""
    op.get_bind().exec_driver_sql(
        _sql(
            "e7b3c6d9a214_normalization_workbench_down.sql"
        )
    )
