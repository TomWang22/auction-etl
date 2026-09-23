"""Persist extracted record labels on warehouse auctions.

Revision ID: a1c3e8f7b240
Revises: 6a8f4d2c9b17
"""

from __future__ import annotations

from pathlib import Path

from alembic import op
from sqlalchemy import text

from auction_etl.classifiers.labels import extract_record_label
from auction_etl.database.collector_views import install_collector_views


revision = "a1c3e8f7b240"
down_revision = "6a8f4d2c9b17"
branch_labels = None
depends_on = None


def _sql(filename: str) -> str:
    """Load adjacent migration SQL."""
    return Path(__file__).with_name(filename).read_text(encoding="utf-8")


def upgrade() -> None:
    """Add auction.label, copy staging labels, and rebuild collector views."""
    bind = op.get_bind()
    bind.execute(text(_sql("a1c3e8f7b240_auction_label_up.sql")))

    rows = bind.execute(
        text(
            """
            SELECT id, title
            FROM warehouse.auction
            WHERE label IS NULL
              AND title IS NOT NULL
            """
        )
    ).mappings()
    for row in rows:
        extracted = extract_record_label(str(row["title"]))
        if not extracted:
            continue
        bind.execute(
            text(
                """
                UPDATE warehouse.auction
                SET label = :label
                WHERE id = :id
                  AND label IS NULL
                """
            ),
            {"label": extracted, "id": row["id"]},
        )

    install_collector_views(bind)


def downgrade() -> None:
    """Drop auction.label after restoring the previous view shape."""
    bind = op.get_bind()
    bind.execute(text(_sql("a1c3e8f7b240_auction_label_down.sql")))
