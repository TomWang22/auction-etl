"""Allow Buyee as an artist marketplace.

Revision ID: 6a8f4d2c9b17

Revises: 25b11c0de001

"""

from __future__ import annotations

from pathlib import Path

from alembic import op
from sqlalchemy import text


revision = "6a8f4d2c9b17"
down_revision = "25b11c0de001"
branch_labels = None
depends_on = None


def _sql(filename: str) -> str:
    """Read migration SQL stored beside this revision."""

    return Path(__file__).with_name(filename).read_text(
        encoding="utf-8"
    )


def upgrade() -> None:
    """Permit Buyee artist marketplace targets."""

    op.get_bind().execute(
        text(
            _sql(
                "6a8f4d2c9b17_allow_buyee_artist_marketplace_up.sql"
            )
        )
    )


def downgrade() -> None:
    """Restore the two-marketplace constraint when safe."""

    op.get_bind().execute(
        text(
            _sql(
                "6a8f4d2c9b17_allow_buyee_artist_marketplace_down.sql"
            )
        )
    )
