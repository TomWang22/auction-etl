"""Phase-D2 account runtime scoping compatibility.

Revision ID: c7f6b1d9e204
Revises: a4d9c2e7f105
"""

from __future__ import annotations

from pathlib import Path

from alembic import op
from sqlalchemy import text


revision = "c7f6b1d9e204"
down_revision = "a4d9c2e7f105"
branch_labels = None
depends_on = None


def _read_sql(filename: str) -> str:
    """Read SQL colocated with this migration."""
    return (
        Path(__file__)
        .with_name(filename)
        .read_text(encoding="utf-8")
    )


def upgrade() -> None:
    """Install nullable account-runtime compatibility constraints."""
    op.get_bind().execute(
        text(
            _read_sql(
                "c7f6b1d9e204_account_runtime_scoping_up.sql"
            )
        )
    )


def downgrade() -> None:
    """Restore the pre-D2 active-job compatibility rule when safe."""
    op.get_bind().execute(
        text(
            _read_sql(
                "c7f6b1d9e204_account_runtime_scoping_down.sql"
            )
        )
    )
