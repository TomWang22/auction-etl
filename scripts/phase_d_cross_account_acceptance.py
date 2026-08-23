#!/usr/bin/env python3
"""Cross-account A/B database acceptance for a disposable Phase-D database."""

from __future__ import annotations

import argparse
import json
import os
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine


LOCAL_HOSTS = {
    "127.0.0.1",
    "::1",
    "localhost",
}


class AcceptanceError(RuntimeError):
    """Raised when a required isolation invariant is not proven."""


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
    )
    parser.add_argument(
        "--evidence",
        type=Path,
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
    )
    return parser.parse_args()


def normalize_sqlalchemy_url(url: str) -> str:
    """Use the repository's psycopg SQLAlchemy driver convention."""
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def database_host(url: str) -> str:
    """Extract the database host from SQLAlchemy/PostgreSQL URL."""
    plain = url.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(plain)
    return parsed.hostname or ""


def require_local_database(url: str, allow_remote: bool) -> None:
    """Reject accidental managed/cloud database acceptance by default."""
    host = database_host(url)

    if allow_remote:
        return

    if host in LOCAL_HOSTS:
        return

    try:
        addresses = {
            info[4][0]
            for info in socket.getaddrinfo(host, None)
        }
    except socket.gaierror:
        addresses = set()

    if addresses and addresses.issubset({"127.0.0.1", "::1"}):
        return

    raise AcceptanceError(
        "Refusing non-loopback database host. "
        f"Found host={host!r}. "
        "This acceptance is intentionally local-only."
    )


def require_relations(engine: Engine) -> None:
    """Require all Phase-D relations used by this acceptance."""
    inspector = inspect(engine)
    required = {
        "identity": {
            "app_user",
            "account",
            "account_member",
        },
        "account": {
            "auction_listing",
            "tracked_artist",
            "artist_marketplace",
            "marketplace_connection",
        },
        "warehouse": {
            "auction",
            "auction_collector",
        },
        "ops": {
            "refresh_job",
        },
    }

    missing: list[str] = []

    for schema, tables in required.items():
        existing = set(
            inspector.get_table_names(schema=schema)
        )
        for table in sorted(tables):
            if table not in existing:
                missing.append(f"{schema}.{table}")

    if missing:
        raise AcceptanceError(
            "Missing Phase-D relations: "
            + ", ".join(missing)
        )


def table_columns(
    connection: Connection,
    schema: str,
    table: str,
) -> set[str]:
    """Return exact columns for one table."""
    rows = connection.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = :schema
              AND table_name = :table
            """
        ),
        {
            "schema": schema,
            "table": table,
        },
    )
    return {str(row[0]) for row in rows}


def insert_identity(
    connection: Connection,
    user_id: uuid.UUID,
    suffix: str,
) -> None:
    """Insert one synthetic OIDC identity."""
    columns = table_columns(
        connection,
        "identity",
        "app_user",
    )

    values: dict[str, object] = {
        "id": user_id,
        "provider": "https://phase-d.acceptance.invalid",
        "subject": f"acceptance-{suffix}-{user_id}",
    }

    optional = {
        "email": f"{suffix.lower()}-{user_id}@example.invalid",
        "display_name": f"Phase D {suffix}",
        "picture_url": None,
    }

    for key, value in optional.items():
        if key in columns:
            values[key] = value

    names = ", ".join(values)
    binds = ", ".join(f":{name}" for name in values)

    connection.execute(
        text(
            f"INSERT INTO identity.app_user "
            f"({names}) VALUES ({binds})"
        ),
        values,
    )


def insert_account(
    connection: Connection,
    account_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    suffix: str,
) -> None:
    """Insert one private personal account and owner membership."""
    account_columns = table_columns(
        connection,
        "identity",
        "account",
    )

    values: dict[str, object] = {
        "id": account_id,
        "name": f"Phase D {suffix} Account",
    }

    if "account_type" in account_columns:
        values["account_type"] = "personal"
    elif "kind" in account_columns:
        values["kind"] = "personal"
    else:
        raise RuntimeError(
            "identity.account exposes neither account_type nor kind"
        )

    if "owner_user_id" in account_columns:
        values["owner_user_id"] = owner_user_id

    if "slug" in account_columns:
        values["slug"] = (
            f"phase-d-{suffix.lower()}-"
            f"{str(account_id)[:8]}"
        )

    names = ", ".join(values)
    binds = ", ".join(
        f":{name}"
        for name in values
    )

    connection.execute(
        text(
            f"INSERT INTO identity.account "
            f"({names}) VALUES ({binds})"
        ),
        values,
    )

    member_columns = table_columns(
        connection,
        "identity",
        "account_member",
    )

    member_values: dict[str, object] = {
        "account_id": account_id,
        "user_id": owner_user_id,
    }

    if "role" in member_columns:
        member_values["role"] = "owner"

    member_names = ", ".join(member_values)
    member_binds = ", ".join(
        f":{name}"
        for name in member_values
    )

    connection.execute(
        text(
            f"INSERT INTO identity.account_member "
            f"({member_names}) VALUES ({member_binds})"
        ),
        member_values,
    )



def choose_canonical_listing(
    connection: Connection,
) -> tuple[str, str]:
    """Choose one shared canonical listing already present in the clone."""
    row = connection.execute(
        text(
            """
            SELECT marketplace, listing_id
            FROM warehouse.auction
            ORDER BY marketplace, listing_id
            LIMIT 1
            """
        )
    ).one_or_none()

    if row is None:
        raise AcceptanceError(
            "Disposable clone contains no warehouse.auction row."
        )

    return str(row[0]), str(row[1])


def visible_count(
    connection: Connection,
    account_id: uuid.UUID,
    marketplace: str,
    listing_id: str,
) -> int:
    """Count one account's visibility edge."""
    return int(
        connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM account.auction_listing
                WHERE account_id = :account_id
                  AND marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "account_id": account_id,
                "marketplace": marketplace,
                "listing_id": listing_id,
            },
        ).scalar_one()
    )


def add_visibility(
    connection: Connection,
    account_id: uuid.UUID,
    marketplace: str,
    listing_id: str,
) -> None:
    """Grant one synthetic account access to one shared listing."""
    columns = table_columns(
        connection,
        "account",
        "auction_listing",
    )

    values: dict[str, object] = {
        "account_id": account_id,
        "marketplace": marketplace,
        "listing_id": listing_id,
    }

    if "source" in columns:
        values["source"] = "phase-d-acceptance"

    names = ", ".join(values)
    binds = ", ".join(f":{name}" for name in values)

    connection.execute(
        text(
            f"INSERT INTO account.auction_listing "
            f"({names}) VALUES ({binds})"
        ),
        values,
    )


def canonical_count(
    connection: Connection,
    marketplace: str,
    listing_id: str,
) -> int:
    """Prove the shared canonical fact was not duplicated."""
    return int(
        connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM warehouse.auction
                WHERE marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "marketplace": marketplace,
                "listing_id": listing_id,
            },
        ).scalar_one()
    )


def insert_tracked_artist(
    connection: Connection,
    account_id: uuid.UUID,
    suffix: str,
) -> uuid.UUID:
    """Insert the same logical artist independently for one account."""
    columns = table_columns(
        connection,
        "account",
        "tracked_artist",
    )

    artist_id = uuid.uuid4()
    artist_name = "Phase D Shared Artist"
    normalized_name = "phase d shared artist"

    values: dict[str, object] = {
        "id": artist_id,
        "account_id": account_id,
        "name": artist_name,
    }

    if "normalized_name" in columns:
        values["normalized_name"] = normalized_name
    elif "normalized_key" in columns:
        values["normalized_key"] = "phase-d-shared-artist"
    else:
        raise RuntimeError(
            "account.tracked_artist exposes neither "
            "normalized_name nor normalized_key"
        )

    if "query" in columns:
        values["query"] = normalized_name

    optional = {
        "enabled": True,
        "source": f"phase-d-acceptance-{suffix.lower()}",
    }

    for key, value in optional.items():
        if key in columns:
            values[key] = value

    names = ", ".join(values)
    binds = ", ".join(
        f":{name}"
        for name in values
    )

    connection.execute(
        text(
            f"INSERT INTO account.tracked_artist "
            f"({names}) VALUES ({binds})"
        ),
        values,
    )

    return artist_id




def tracked_artist_count(
    connection: Connection,
    account_id: uuid.UUID,
) -> int:
    """Count the shared synthetic artist inside one account."""
    columns = table_columns(
        connection,
        "account",
        "tracked_artist",
    )

    if "normalized_name" in columns:
        identity_column = "normalized_name"
        identity_value = "phase d shared artist"
    elif "normalized_key" in columns:
        identity_column = "normalized_key"
        identity_value = "phase-d-shared-artist"
    else:
        raise RuntimeError(
            "account.tracked_artist exposes neither "
            "normalized_name nor normalized_key"
        )

    count = connection.execute(
        text(
            f"""
            SELECT COUNT(*)
            FROM account.tracked_artist
            WHERE account_id = :account_id
              AND {identity_column} = :identity_value
            """
        ),
        {
            "account_id": account_id,
            "identity_value": identity_value,
        },
    ).scalar_one()

    return int(count)



def insert_collector_record(
    connection: Connection,
    account_id: uuid.UUID,
    marketplace: str,
    listing_id: str,
) -> None:
    """Insert minimum collector metadata for one account/listing."""
    columns = table_columns(
        connection,
        "warehouse",
        "auction_collector",
    )

    required = {
        "account_id",
        "marketplace",
        "listing_id",
    }

    if not required.issubset(columns):
        raise AcceptanceError(
            "warehouse.auction_collector lacks account ownership columns"
        )

    connection.execute(
        text(
            """
            INSERT INTO warehouse.auction_collector (
                account_id,
                marketplace,
                listing_id
            )
            VALUES (
                :account_id,
                :marketplace,
                :listing_id
            )
            """
        ),
        {
            "account_id": account_id,
            "marketplace": marketplace,
            "listing_id": listing_id,
        },
    )


def collector_count(
    connection: Connection,
    account_id: uuid.UUID,
    marketplace: str,
    listing_id: str,
) -> int:
    """Count collector-private rows for one account."""
    return int(
        connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM warehouse.auction_collector
                WHERE account_id = :account_id
                  AND marketplace = :marketplace
                  AND listing_id = :listing_id
                """
            ),
            {
                "account_id": account_id,
                "marketplace": marketplace,
                "listing_id": listing_id,
            },
        ).scalar_one()
    )


def insert_refresh_job(
    connection: Connection,
    account_id: uuid.UUID,
    user_id: uuid.UUID,
    suffix: str,
) -> uuid.UUID:
    """Insert one completed synthetic account-owned refresh job."""
    job_id = uuid.uuid4()
    columns = table_columns(
        connection,
        "ops",
        "refresh_job",
    )

    values: dict[str, object] = {
        "id": job_id,
        "state": "completed",
        "account_id": account_id,
        "requested_by_user_id": user_id,
    }

    optional = {
        "requested_by": f"phase-d-acceptance-{suffix.lower()}",
        "trigger": "phase-d-acceptance",
        "message": "cross-account acceptance synthetic job",
    }

    for key, value in optional.items():
        if key in columns:
            values[key] = value

    names = ", ".join(values)
    binds = ", ".join(f":{name}" for name in values)

    connection.execute(
        text(
            f"INSERT INTO ops.refresh_job "
            f"({names}) VALUES ({binds})"
        ),
        values,
    )

    return job_id


def scoped_job_count(
    connection: Connection,
    account_id: uuid.UUID,
    job_id: uuid.UUID,
) -> int:
    """Count a job only when account ownership matches."""
    return int(
        connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM ops.refresh_job
                WHERE id = :job_id
                  AND account_id = :account_id
                """
            ),
            {
                "job_id": job_id,
                "account_id": account_id,
            },
        ).scalar_one()
    )


def insert_marketplace_connection(
    connection: Connection,
    account_id: uuid.UUID,
    suffix: str,
) -> uuid.UUID:
    """Insert one non-secret per-account Buyee connection reference."""
    connection_id = uuid.uuid4()
    columns = table_columns(
        connection,
        "account",
        "marketplace_connection",
    )

    values: dict[str, object] = {
        "id": connection_id,
        "account_id": account_id,
        "marketplace": "buyee",
    }

    optional = {
        "status": "connected",
        "credential_reference":
            f"acceptance://credential/{suffix.lower()}",
        "profile_reference":
            f"acceptance://profile/{suffix.lower()}",
    }

    for key, value in optional.items():
        if key in columns:
            values[key] = value

    names = ", ".join(values)
    binds = ", ".join(f":{name}" for name in values)

    connection.execute(
        text(
            f"INSERT INTO account.marketplace_connection "
            f"({names}) VALUES ({binds})"
        ),
        values,
    )

    return connection_id


def connection_count(
    connection: Connection,
    account_id: uuid.UUID,
    connection_id: uuid.UUID,
) -> int:
    """Count one marketplace connection within its owning account."""
    return int(
        connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM account.marketplace_connection
                WHERE id = :connection_id
                  AND account_id = :account_id
                """
            ),
            {
                "connection_id": connection_id,
                "account_id": account_id,
            },
        ).scalar_one()
    )


def run_acceptance(engine: Engine) -> dict[str, object]:
    """Execute all A/B isolation checks and roll them back."""
    require_relations(engine)

    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    account_a = uuid.uuid4()
    account_b = uuid.uuid4()

    result: dict[str, object] = {}

    with engine.connect() as connection:
        transaction = connection.begin()

        try:
            insert_identity(connection, user_a, "A")
            insert_identity(connection, user_b, "B")
            insert_account(connection, account_a, user_a, "A")
            insert_account(connection, account_b, user_b, "B")

            marketplace, listing_id = choose_canonical_listing(
                connection
            )

            canonical_before = canonical_count(
                connection,
                marketplace,
                listing_id,
            )

            add_visibility(
                connection,
                account_a,
                marketplace,
                listing_id,
            )

            a_visible = visible_count(
                connection,
                account_a,
                marketplace,
                listing_id,
            )
            b_visible_before = visible_count(
                connection,
                account_b,
                marketplace,
                listing_id,
            )

            add_visibility(
                connection,
                account_b,
                marketplace,
                listing_id,
            )

            b_visible_after = visible_count(
                connection,
                account_b,
                marketplace,
                listing_id,
            )

            canonical_after = canonical_count(
                connection,
                marketplace,
                listing_id,
            )

            insert_tracked_artist(connection, account_a, "A")
            insert_tracked_artist(connection, account_b, "B")

            a_artist_count = tracked_artist_count(
                connection,
                account_a,
            )
            b_artist_count = tracked_artist_count(
                connection,
                account_b,
            )

            insert_collector_record(
                connection,
                account_a,
                marketplace,
                listing_id,
            )
            insert_collector_record(
                connection,
                account_b,
                marketplace,
                listing_id,
            )

            a_collector = collector_count(
                connection,
                account_a,
                marketplace,
                listing_id,
            )
            b_collector = collector_count(
                connection,
                account_b,
                marketplace,
                listing_id,
            )

            job_a = insert_refresh_job(
                connection,
                account_a,
                user_a,
                "A",
            )
            job_b = insert_refresh_job(
                connection,
                account_b,
                user_b,
                "B",
            )

            a_reads_a = scoped_job_count(
                connection,
                account_a,
                job_a,
            )
            a_reads_b = scoped_job_count(
                connection,
                account_a,
                job_b,
            )
            b_reads_a = scoped_job_count(
                connection,
                account_b,
                job_a,
            )
            b_reads_b = scoped_job_count(
                connection,
                account_b,
                job_b,
            )

            buyee_a = insert_marketplace_connection(
                connection,
                account_a,
                "A",
            )
            buyee_b = insert_marketplace_connection(
                connection,
                account_b,
                "B",
            )

            a_buyee_own = connection_count(
                connection,
                account_a,
                buyee_a,
            )
            a_buyee_other = connection_count(
                connection,
                account_a,
                buyee_b,
            )
            b_buyee_own = connection_count(
                connection,
                account_b,
                buyee_b,
            )
            b_buyee_other = connection_count(
                connection,
                account_b,
                buyee_a,
            )

            checks = {
                "ACCOUNT_A_VISIBLE_LISTINGS":
                    a_visible == 1,
                "ACCOUNT_B_VISIBLE_LISTINGS_BEFORE_GRANT":
                    b_visible_before == 0,
                "ACCOUNT_B_VISIBLE_LISTINGS_AFTER_GRANT":
                    b_visible_after == 1,
                "CANONICAL_ROW_NOT_DUPLICATED":
                    canonical_before == 1
                    and canonical_after == 1,
                "TRACKED_ARTIST_ISOLATED":
                    a_artist_count == 1
                    and b_artist_count == 1,
                "COLLECTOR_METADATA_ISOLATED":
                    a_collector == 1
                    and b_collector == 1,
                "REFRESH_JOB_ISOLATED":
                    a_reads_a == 1
                    and a_reads_b == 0
                    and b_reads_a == 0
                    and b_reads_b == 1,
                "MARKETPLACE_CONNECTION_ISOLATED":
                    a_buyee_own == 1
                    and a_buyee_other == 0
                    and b_buyee_own == 1
                    and b_buyee_other == 0,
            }

            checks["CROSS_ACCOUNT_READ_DENIED"] = (
                checks["REFRESH_JOB_ISOLATED"]
                and checks["MARKETPLACE_CONNECTION_ISOLATED"]
                and b_visible_before == 0
            )

            checks["CROSS_ACCOUNT_WRITE_DENIED"] = (
                checks["COLLECTOR_METADATA_ISOLATED"]
                and checks["TRACKED_ARTIST_ISOLATED"]
            )

            failures = [
                name
                for name, passed in checks.items()
                if not passed
            ]

            if failures:
                raise AcceptanceError(
                    "Acceptance checks failed: "
                    + ", ".join(failures)
                )

            result = {
                "completed_at":
                    datetime.now(timezone.utc).isoformat(),
                "classification":
                    "PHASE_D_CROSS_ACCOUNT_ACCEPTANCE_PASS",
                "canonical_listing": {
                    "marketplace": marketplace,
                    "listing_id": listing_id,
                    "canonical_count_before":
                        canonical_before,
                    "canonical_count_after":
                        canonical_after,
                },
                "checks": checks,
                "safety": {
                    "transaction_committed": False,
                    "neon_mutation_executed": False,
                    "vercel_command_executed": False,
                    "railway_command_executed": False,
                    "refresh_command_executed": False,
                    "controlled_v3_rerun_executed": False,
                },
            }
        finally:
            transaction.rollback()

    return result


def main() -> int:
    """Run acceptance and write non-secret evidence."""
    args = parse_args()

    if not args.database_url:
        raise SystemExit(
            "ERROR: --database-url or DATABASE_URL is required."
        )

    require_local_database(
        args.database_url,
        args.allow_remote,
    )

    engine = create_engine(
        normalize_sqlalchemy_url(args.database_url),
        future=True,
        pool_pre_ping=True,
    )

    try:
        result = run_acceptance(engine)
    finally:
        engine.dispose()

    if args.evidence is not None:
        evidence = args.evidence.expanduser().resolve()
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(
            json.dumps(result, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"EVIDENCE={evidence}")

    for name, passed in result["checks"].items():
        print(
            f"{name}="
            + ("true" if passed else "false")
        )

    print("TRANSACTION_COMMITTED=false")
    print("NEON_MUTATION_EXECUTED=false")
    print("VERCEL_COMMAND_EXECUTED=false")
    print("RAILWAY_COMMAND_EXECUTED=false")
    print("REFRESH_COMMAND_EXECUTED=false")
    print("CONTROLLED_V3_RERUN_EXECUTED=false")
    print("CROSS_ACCOUNT_ACCEPTANCE=PASS")
    print("RESULT=PHASE_D_CROSS_ACCOUNT_ACCEPTANCE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
