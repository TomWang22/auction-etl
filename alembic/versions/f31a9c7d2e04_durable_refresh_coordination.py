"""Add durable refresh coordination tables.

Revision ID: f31a9c7d2e04
Revises: c8b4d7e2a619
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from alembic import op


revision: str = "f31a9c7d2e04"
down_revision: str | None = "c8b4d7e2a619"
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
    """Install durable refresh coordination."""
    op.get_bind().exec_driver_sql(
        _sql(
            "f31a9c7d2e04_durable_refresh_coordination_up.sql"
        )
    )


def downgrade() -> None:
    """Remove durable refresh coordination."""
    op.get_bind().exec_driver_sql(
        _sql(
            "f31a9c7d2e04_durable_refresh_coordination_down.sql"
        )
    )
