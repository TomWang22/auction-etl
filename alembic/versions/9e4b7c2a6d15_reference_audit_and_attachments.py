"""Add reference audit history and evidence attachments.

Revision ID: 9e4b7c2a6d15
Revises: 7c3e8a1d5f42
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from alembic import op


revision: str = "9e4b7c2a6d15"
down_revision: str | None = "7c3e8a1d5f42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _sql(filename: str) -> str:
    """Load SQL adjacent to this revision."""
    return (
        Path(__file__)
        .with_name(filename)
        .read_text(encoding="utf-8")
    )


def upgrade() -> None:
    """Install audit, attachment, and batch history."""
    op.get_bind().exec_driver_sql(
        _sql(
            "9e4b7c2a6d15_reference_audit_and_attachments_up.sql"
        )
    )


def downgrade() -> None:
    """Remove audit, attachment, and batch history."""
    op.get_bind().exec_driver_sql(
        _sql(
            "9e4b7c2a6d15_reference_audit_and_attachments_down.sql"
        )
    )
