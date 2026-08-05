"""Add new-auction assignment review and completeness alerts."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "c8b4d7e2a619"
down_revision = "d4e8b1c7a903"
branch_labels = None
depends_on = None


def _sql(filename: str) -> str:
    """Read migration SQL stored beside this revision."""
    return (
        Path(__file__)
        .with_name(filename)
        .read_text(encoding="utf-8")
    )


def upgrade() -> None:
    """Install assignment audit, queue, and alert views."""
    op.get_bind().exec_driver_sql(
        _sql(
            "c8b4d7e2a619_new_auction_intake_queue_and_alerts_up.sql"
        )
    )


def downgrade() -> None:
    """Remove assignment audit, queue, and alert views."""
    op.get_bind().exec_driver_sql(
        _sql(
            "c8b4d7e2a619_new_auction_intake_queue_and_alerts_down.sql"
        )
    )
