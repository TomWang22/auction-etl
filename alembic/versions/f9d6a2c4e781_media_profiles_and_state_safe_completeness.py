"""Add configurable media profiles and immutable profile audit."""

from __future__ import annotations

from pathlib import Path

from alembic import op


revision = "f9d6a2c4e781"
down_revision = "e7b3c6d9a214"
branch_labels = None
depends_on = None


def _sql(filename: str) -> str:
    """Load adjacent migration SQL."""
    return (
        Path(__file__)
        .with_name(filename)
        .read_text(encoding="utf-8")
    )


def upgrade() -> None:
    """Install media-profile administration."""
    op.get_bind().exec_driver_sql(
        _sql(
            "f9d6a2c4e781_media_profiles_and_state_safe_completeness_up.sql"
        )
    )


def downgrade() -> None:
    """Remove media-profile administration."""
    op.get_bind().exec_driver_sql(
        _sql(
            "f9d6a2c4e781_media_profiles_and_state_safe_completeness_down.sql"
        )
    )
