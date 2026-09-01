"""Widen crawl-job source provenance.

Revision ID: 25b11c0de001
Revises: e2f7a1c9d4b6
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "25b11c0de001"
down_revision = "e2f7a1c9d4b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Remove the artificial 32-character provenance limit."""

    op.alter_column(
        "crawl_job",
        "source",
        schema="system",
        existing_type=sa.String(length=32),
        type_=sa.Text(),
        existing_nullable=False,
        postgresql_using="source::text",
    )


def downgrade() -> None:
    """Restore VARCHAR(32) only when existing values fit."""

    connection = op.get_bind()

    oversized = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM system.crawl_job
            WHERE char_length(source) > 32
            """
        )
    ).scalar_one()

    if int(oversized) != 0:
        raise RuntimeError(
            "Cannot downgrade system.crawl_job.source to VARCHAR(32): "
            "existing provenance values exceed 32 characters."
        )

    op.alter_column(
        "crawl_job",
        "source",
        schema="system",
        existing_type=sa.Text(),
        type_=sa.String(length=32),
        existing_nullable=False,
        postgresql_using="source::varchar(32)",
    )
