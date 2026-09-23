"""Persist Discogs identity fields and rebuild collector views.

Revision ID: b7e4c1a9d352
Revises: a1c3e8f7b240
"""

from __future__ import annotations

from pathlib import Path

from alembic import op
from sqlalchemy import text

from auction_etl.database.collector_views import install_collector_views


revision = "b7e4c1a9d352"
down_revision = "a1c3e8f7b240"
branch_labels = None
depends_on = None


def _sql(filename: str) -> str:
    """Load adjacent migration SQL."""
    return Path(__file__).with_name(filename).read_text(encoding="utf-8")


def upgrade() -> None:
    """Add identity schema, copy listing images, and rebuild collector views."""
    bind = op.get_bind()
    bind.execute(text(_sql("b7e4c1a9d352_discogs_identity_up.sql")))
    install_collector_views(bind)


def downgrade() -> None:
    """Drop Discogs identity columns after dropping collector views."""
    bind = op.get_bind()
    bind.execute(text(_sql("b7e4c1a9d352_discogs_identity_down.sql")))
