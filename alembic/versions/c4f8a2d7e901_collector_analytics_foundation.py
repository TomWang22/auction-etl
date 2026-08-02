"""Collector analytics foundation.

Revision ID: c4f8a2d7e901
Revises: be7b9855a5dc
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "c4f8a2d7e901"
down_revision = "be7b9855a5dc"
branch_labels = None
depends_on = None


def _read_sql(filename: str) -> str:
    return (
        Path(__file__)
        .with_name(filename)
        .read_text(encoding="utf-8")
    )


def upgrade() -> None:
    """Install collector analytics relations and views."""
    op.get_bind().exec_driver_sql(
        _read_sql(
            "c4f8a2d7e901_collector_analytics_up.sql"
        )
    )


def downgrade() -> None:
    """Remove collector analytics relations and views."""
    op.get_bind().exec_driver_sql(
        _read_sql(
            "c4f8a2d7e901_collector_analytics_down.sql"
        )
    )
