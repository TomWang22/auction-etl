"""Add the Phase-D identity/account foundation.

Revision ID: a4d9c2e7f105
Revises: f31a9c7d2e04
"""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "a4d9c2e7f105"
down_revision = "f31a9c7d2e04"
branch_labels = None
depends_on = None


def _sql(name: str) -> str:
    """Load adjacent reviewed SQL."""
    return (
        Path(__file__)
        .with_name(name)
        .read_text(encoding="utf-8")
    )


def upgrade() -> None:
    """Install the additive account foundation."""
    op.execute(
        _sql("a4d9c2e7f105_account_identity_foundation_up.sql")
    )


def downgrade() -> None:
    """Remove the additive account foundation."""
    op.execute(
        _sql("a4d9c2e7f105_account_identity_foundation_down.sql")
    )
