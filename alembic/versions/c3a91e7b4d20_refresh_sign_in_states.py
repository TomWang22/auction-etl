"""Allow Buyee sign-in and eBay handoff as durable marketplace states.

Revision ID: c3a91e7b4d20
Revises: b7e4c1a9d352
"""

from __future__ import annotations

from alembic import op


revision = "c3a91e7b4d20"
down_revision = "b7e4c1a9d352"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Store authentication_required and awaiting_handoff instead of crashing."""
    op.execute(
        """
        ALTER TABLE ops.refresh_marketplace
            DROP CONSTRAINT refresh_marketplace_state_check
        """
    )
    op.execute(
        """
        ALTER TABLE ops.refresh_marketplace
            ADD CONSTRAINT refresh_marketplace_state_check
            CHECK (
                state IN (
                    'waiting',
                    'running',
                    'done',
                    'failed',
                    'skipped',
                    'authentication_required',
                    'awaiting_handoff'
                )
            )
        """
    )


def downgrade() -> None:
    """Restore the original five marketplace states."""
    op.execute(
        """
        ALTER TABLE ops.refresh_marketplace
            DROP CONSTRAINT refresh_marketplace_state_check
        """
    )
    op.execute(
        """
        ALTER TABLE ops.refresh_marketplace
            ADD CONSTRAINT refresh_marketplace_state_check
            CHECK (
                state IN (
                    'waiting',
                    'running',
                    'done',
                    'failed',
                    'skipped'
                )
            )
        """
    )
