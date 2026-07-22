"""add uniqueness constraints

Revision ID: be7b9855a5dc
Revises: 0428279b6f87
Create Date: 2026-07-22

"""

from typing import Sequence, Union

from alembic import op


revision: str = "be7b9855a5dc"
down_revision: Union[str, Sequence[str], None] = "0428279b6f87"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_auction_marketplace_listing",
        "auction",
        ["marketplace", "listing_id"],
        schema="warehouse",
    )

    op.create_unique_constraint(
        "uq_page_sha256",
        "page",
        ["sha256"],
        schema="raw",
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_page_sha256",
        "page",
        schema="raw",
        type_="unique",
    )

    op.drop_constraint(
        "uq_auction_marketplace_listing",
        "auction",
        schema="warehouse",
        type_="unique",
    )
