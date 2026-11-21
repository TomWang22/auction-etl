"""Allow five refresh marketplaces in ops.refresh_marketplace.

Revision ID: e8f3c1a0b7d2
Revises: d5e8f2a1b903
"""

from __future__ import annotations

from pathlib import Path

from alembic import op
from sqlalchemy import text


revision = "e8f3c1a0b7d2"
down_revision = "d5e8f2a1b903"
branch_labels = None
depends_on = None


def _sql(filename: str) -> str:
    """Read migration SQL stored beside this revision."""

    return Path(__file__).with_name(filename).read_text(encoding="utf-8")


def upgrade() -> None:
    """Raise ordinal ceiling to 5 and allow rate_limited marketplace state."""

    op.get_bind().execute(
        text(_sql("e8f3c1a0b7d2_refresh_marketplace_five_sources_up.sql"))
    )


def downgrade() -> None:
    """Restore three-marketplace ordinal ceiling when safe."""

    op.get_bind().execute(
        text(_sql("e8f3c1a0b7d2_refresh_marketplace_five_sources_down.sql"))
    )
