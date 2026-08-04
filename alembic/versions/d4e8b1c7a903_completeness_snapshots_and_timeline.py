"""Add immutable completeness snapshots and listing timelines."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "d4e8b1c7a903"
down_revision = "f9d6a2c4e781"
branch_labels = None
depends_on = None


def _sql(name: str) -> str:
    """Read SQL stored beside this migration."""
    return (
        Path(__file__)
        .with_name(name)
        .read_text(encoding="utf-8")
    )


def upgrade() -> None:
    """Install completeness snapshots and automatic triggers."""
    op.get_bind().exec_driver_sql(
        _sql(
            "d4e8b1c7a903_completeness_snapshots_and_timeline_up.sql"
        )
    )


def downgrade() -> None:
    """Remove completeness snapshots and automatic triggers."""
    op.get_bind().exec_driver_sql(
        _sql(
            "d4e8b1c7a903_completeness_snapshots_and_timeline_down.sql"
        )
    )
