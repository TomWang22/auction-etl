"""Allow Yahoo Auctions + フリマ marketplace keys.

Revision ID: d5e8f2a1b903
Revises: c3a91e7b4d20
"""

from __future__ import annotations

from pathlib import Path

from alembic import op
from sqlalchemy import text


revision = "d5e8f2a1b903"
down_revision = "c3a91e7b4d20"
branch_labels = None
depends_on = None


def _sql(filename: str) -> str:
    """Read migration SQL stored beside this revision."""

    return Path(__file__).with_name(filename).read_text(encoding="utf-8")


def upgrade() -> None:
    """Permit yahoo_auction and yahoo_fleamarket across account/ops checks."""

    op.get_bind().execute(
        text(_sql("d5e8f2a1b903_allow_yahoo_jp_marketplaces_up.sql"))
    )


def downgrade() -> None:
    """Restore three-marketplace checks when no yahoo_* rows remain."""

    op.get_bind().execute(
        text(_sql("d5e8f2a1b903_allow_yahoo_jp_marketplaces_down.sql"))
    )
