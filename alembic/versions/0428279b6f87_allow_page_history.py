"""allow page history"""

from typing import Sequence, Union

from alembic import op

revision: str = "0428279b6f87"
down_revision: Union[str, Sequence[str], None] = "c4aba410158b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "page_url_key",
        "page",
        schema="raw",
        type_="unique",
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "page_url_key",
        "page",
        ["url"],
        schema="raw",
    )
