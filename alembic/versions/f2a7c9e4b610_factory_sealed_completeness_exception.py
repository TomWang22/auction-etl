"""Add a conservative factory-sealed completeness exception.

Revision ID: f2a7c9e4b610
Revises: d8a41f6c2b70
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "f2a7c9e4b610"
down_revision = "d8a41f6c2b70"
branch_labels = None
depends_on = None


def _read_sql(filename: str) -> str:
    """Read SQL stored beside this migration."""
    return (
        Path(__file__)
        .with_name(filename)
        .read_text(encoding="utf-8")
    )


def upgrade() -> None:
    """Install factory-sealed completeness classification."""
    op.execute(
        _read_sql(
            "f2a7c9e4b610_factory_sealed_completeness_exception_up.sql"
        )
    )


def downgrade() -> None:
    """Restore the previous completeness definition."""
    op.execute(
        _read_sql(
            "f2a7c9e4b610_factory_sealed_completeness_exception_down.sql"
        )
    )
