#!/usr/bin/env python3
"""Evidence-gated rollback of the Phase-D owner backfill."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection


def sqlalchemy_url(value: str) -> str:
    """Use SQLAlchemy's Psycopg 3 dialect."""
    if value.startswith("postgresql+psycopg://"):
        return value
    if value.startswith("postgresql://"):
        return value.replace(
            "postgresql://",
            "postgresql+psycopg://",
            1,
        )
    return value


def count_account_rows(
    connection: Connection,
    relation: str,
    account_id: str,
) -> int:
    """Count account-owned rows in a trusted relation."""
    return int(
        connection.execute(
            text(
                f"""
                SELECT COUNT(*)
                FROM {relation}
                WHERE account_id = :account_id
                """
            ),
            {"account_id": account_id},
        ).scalar_one()
    )


def parse_args() -> argparse.Namespace:
    """Parse rollback arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> int:
    """Refuse rollback if account state changed after the backfill."""
    args = parse_args()
    evidence: dict[str, Any] = json.loads(
        args.evidence.expanduser().read_text(encoding="utf-8")
    )
    if evidence.get("classification") != "PHASE_D_OWNER_BACKFILL_APPLIED":
        raise SystemExit(
            "ERROR: evidence is not a Phase-D owner-backfill record."
        )

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("ERROR: DATABASE_URL is required.")

    account_id = str(evidence["account_id"])
    user_id = str(evidence["user_id"])
    engine = create_engine(
        sqlalchemy_url(database_url),
        pool_pre_ping=True,
    )

    with engine.connect() as connection:
        listing_count = count_account_rows(
            connection,
            "account.auction_listing",
            account_id,
        )
        artist_count = count_account_rows(
            connection,
            "account.tracked_artist",
            account_id,
        )

        if listing_count != int(evidence["listing_count"]):
            raise SystemExit(
                "ERROR: account listing count changed after backfill; "
                "rollback refused."
            )
        if artist_count != int(evidence["tracked_artist_count"]):
            raise SystemExit(
                "ERROR: tracked-artist count changed after backfill; "
                "rollback refused."
            )

        for relation, expected in evidence.get(
            "legacy_updates",
            {},
        ).items():
            current = count_account_rows(
                connection,
                relation,
                account_id,
            )
            if current != int(expected):
                raise SystemExit(
                    f"ERROR: {relation} drifted after backfill: "
                    f"expected {expected}; found {current}."
                )

    print(f"OWNER_ACCOUNT_ID={account_id}")
    print(f"OWNER_USER_ID={user_id}")
    print(f"LISTING_COUNT={listing_count}")
    print(f"TRACKED_ARTIST_COUNT={artist_count}")
    print("ROLLBACK_DRIFT_CHECK=PASS")

    if not args.apply:
        print("MODE=DRY_RUN")
        print("DATABASE_MUTATION_EXECUTED=false")
        return 0

    with engine.begin() as connection:
        for relation in evidence.get("legacy_updates", {}):
            if relation == "ops.refresh_job":
                continue
            connection.execute(
                text(
                    f"""
                    UPDATE {relation}
                    SET account_id = NULL
                    WHERE account_id = :account_id
                    """
                ),
                {"account_id": account_id},
            )

        connection.execute(
            text(
                """
                UPDATE ops.refresh_job
                SET
                    account_id = NULL,
                    requested_by_user_id = NULL
                WHERE account_id = :account_id
                  AND requested_by_user_id = :user_id
                """
            ),
            {"account_id": account_id, "user_id": user_id},
        )

        connection.execute(
            text(
                """
                DELETE FROM account.auction_listing
                WHERE account_id = :account_id
                """
            ),
            {"account_id": account_id},
        )
        connection.execute(
            text(
                """
                DELETE FROM account.tracked_artist
                WHERE account_id = :account_id
                """
            ),
            {"account_id": account_id},
        )

        if not bool(evidence.get("account_preexisting", True)):
            connection.execute(
                text(
                    """
                    DELETE FROM identity.account
                    WHERE id = :account_id
                    """
                ),
                {"account_id": account_id},
            )

        if not bool(evidence.get("user_preexisting", True)):
            memberships = int(
                connection.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM identity.account_member
                        WHERE user_id = :user_id
                        """
                    ),
                    {"user_id": user_id},
                ).scalar_one()
            )
            if memberships == 0:
                connection.execute(
                    text(
                        """
                        DELETE FROM identity.app_user
                        WHERE id = :user_id
                        """
                    ),
                    {"user_id": user_id},
                )

    print("MODE=APPLY")
    print("OWNER_BACKFILL_ROLLED_BACK=true")
    print("CANONICAL_AUCTION_ROWS_DELETED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
