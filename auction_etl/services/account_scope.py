"""Account-scope primitives for SQLAlchemy data access."""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Iterator
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine


_ALIAS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def account_listing_exists_sql(relation_alias: str) -> str:
    """Return the account visibility predicate for a listing relation."""
    if not _ALIAS_RE.fullmatch(relation_alias):
        raise ValueError(f"Unsafe SQL alias: {relation_alias!r}")

    return f"""
        EXISTS (
            SELECT 1
            FROM account.auction_listing AS account_listing
            WHERE account_listing.account_id = :account_id
              AND account_listing.marketplace =
                  {relation_alias}.marketplace
              AND account_listing.listing_id =
                  {relation_alias}.listing_id
        )
    """


def set_transaction_account_context(
    connection: Connection,
    *,
    account_id: UUID,
    user_id: UUID,
) -> None:
    """Set transaction-local PostgreSQL identity for later RLS."""
    connection.execute(
        text(
            """
            SELECT
                set_config(
                    'collector_ledger.account_id',
                    :account_id,
                    true
                ),
                set_config(
                    'collector_ledger.user_id',
                    :user_id,
                    true
                )
            """
        ),
        {
            "account_id": str(account_id),
            "user_id": str(user_id),
        },
    )


@contextmanager
def account_transaction(
    engine: Engine,
    *,
    account_id: UUID,
    user_id: UUID,
) -> Iterator[Connection]:
    """Open a transaction with account/user context established."""
    with engine.begin() as connection:
        set_transaction_account_context(
            connection,
            account_id=account_id,
            user_id=user_id,
        )
        yield connection
