from __future__ import annotations

from pathlib import Path

from alembic import op
from sqlalchemy import text

revision = "e2f7a1c9d4b6"
down_revision = "c7f6b1d9e204"
branch_labels = None
depends_on = None


def _sql(filename: str) -> str:
    """Read migration SQL stored beside this revision."""

    return Path(__file__).with_name(filename).read_text(encoding="utf-8")


def upgrade() -> None:
    """Install durable refresh inputs and live visibility counters."""

    op.get_bind().execute(
        text(
            _sql(
                "e2f7a1c9d4b6_refresh_inputs_and_live_visibility_up.sql"
            )
        )
    )


def downgrade() -> None:
    """Remove durable refresh inputs and live visibility counters."""

    op.get_bind().execute(
        text(
            _sql(
                "e2f7a1c9d4b6_refresh_inputs_and_live_visibility_down.sql"
            )
        )
    )
