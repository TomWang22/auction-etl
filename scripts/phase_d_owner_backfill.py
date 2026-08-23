#!/usr/bin/env python3
"""Dry-run-first migration of the existing workspace to its owner account."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from auction_etl.auth.context import AuthenticatedPrincipal
from auction_etl.services.account_access import (
    stable_personal_account_id,
    stable_user_id,
)
from auction_etl.services.artist_tracking import load_tracking_state


LEGACY_ACCOUNT_RELATIONS = (
    "warehouse.auction_collector",
    "warehouse.auction_pressing_assignment",
    "system.new_auction_assignment_queue",
    "system.auction_pressing_assignment_audit_event",
    "system.listing_completeness_snapshot",
    "system.listing_completeness_timeline",
    "system.current_listing_completeness_alert",
)


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


def resolve_review_relation(connection: Connection) -> str:
    """Resolve the same native review relation used by the current UI."""
    row = connection.execute(
        text(
            """
            SELECT
                to_regclass('warehouse.auction_collector_review'),
                to_regclass('warehouse.auction_collector_effective')
            """
        )
    ).one()
    if row[0]:
        return "warehouse.auction_collector_review"
    if row[1]:
        return "warehouse.auction_collector_effective"
    return "warehouse.auction"


def native_identities(connection: Connection) -> set[tuple[str, str]]:
    """Load current native Review identities."""
    relation = resolve_review_relation(connection)
    rows = connection.execute(
        text(
            f"""
            SELECT marketplace::text, listing_id::text
            FROM {relation}
            WHERE marketplace IS NOT NULL
              AND listing_id IS NOT NULL
            """
        )
    )
    return {
        (str(m).strip().casefold(), str(i).strip())
        for m, i in rows
        if str(m).strip() and str(i).strip()
    }


def gripsweat_identities(database_url: str) -> set[tuple[str, str]]:
    """Load Gripsweat-only identities through the existing integration."""
    from auction_etl.reporting.main_review_integration import (
        load_gripsweat_records,
    )

    frame = load_gripsweat_records(database_url=database_url)
    if frame.empty:
        return set()
    required = {"marketplace", "listing_id"}
    if not required.issubset(frame.columns):
        raise RuntimeError(
            "Gripsweat reporting surface lacks listing identity columns."
        )

    return {
        (
            str(row.marketplace).strip().casefold(),
            str(row.listing_id).strip(),
        )
        for row in frame[
            ["marketplace", "listing_id"]
        ].itertuples(index=False)
        if str(row.marketplace).strip()
        and str(row.listing_id).strip()
    }


def current_listing_manifest(
    engine: Engine,
    database_url: str,
) -> set[tuple[str, str]]:
    """Build current unified Review listing identities."""
    with engine.connect() as connection:
        native = native_identities(connection)
    return native.union(gripsweat_identities(database_url))


def current_artists() -> tuple[list[dict[str, Any]], int]:
    """Load the existing runtime-backed artist model losslessly."""
    state = load_tracking_state()
    artists = state.get("artists", [])
    if not isinstance(artists, list):
        raise RuntimeError("Artist state has no artists list.")

    searches = 0
    clean: list[dict[str, Any]] = []
    for artist in artists:
        if not isinstance(artist, dict):
            continue
        clean.append(artist)
        targets = artist.get("targets", {})
        if isinstance(targets, dict):
            searches += sum(
                isinstance(target, dict)
                and bool(target.get("enabled", False))
                for target in targets.values()
            )
    return clean, searches


def relation_exists(connection: Connection, relation: str) -> bool:
    """Return whether a relation exists."""
    return (
        connection.execute(
            text("SELECT to_regclass(:relation)"),
            {"relation": relation},
        ).scalar_one()
        is not None
    )


IMMUTABLE_LEGACY_ACCOUNT_RELATIONS = frozenset(
    {
        "system.auction_pressing_assignment_audit_event",
        "system.listing_completeness_snapshot",
    }
)

def relation_kind(
    connection: Connection,
    relation: str,
) -> str | None:
    """Return PostgreSQL relkind for one qualified relation."""
    return connection.execute(
        text(
            """
            SELECT target_relation.relkind::text
            FROM pg_class AS target_relation
            WHERE target_relation.oid = to_regclass(:relation)
            """
        ),
        {"relation": relation},
    ).scalar_one_or_none()


def should_backfill_account_relation(
    connection: Connection,
    relation: str,
) -> bool:
    """Return whether an existing relation needs direct account backfill."""
    if relation in IMMUTABLE_LEGACY_ACCOUNT_RELATIONS:
        return False

    kind = relation_kind(
        connection,
        relation,
    )

    if kind is None:
        return False

    if kind in {"v", "m"}:
        return False

    if kind not in {"r", "p"}:
        raise RuntimeError(
            "Unsupported Phase D legacy relation type: "
            f"{relation} has PostgreSQL relkind {kind!r}"
        )

    if not has_account_column(
        connection,
        relation,
    ):
        raise RuntimeError(
            f"D1 account_id column missing: {relation}"
        )

    return True


def has_account_column(connection: Connection, relation: str) -> bool:
    """Return whether D1 added account_id."""
    schema, table_name = relation.split(".", 1)
    return bool(
        connection.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = :schema
                      AND table_name = :table_name
                      AND column_name = 'account_id'
                )
                """
            ),
            {"schema": schema, "table_name": table_name},
        ).scalar_one()
    )


def normalize_name(value: str) -> str:
    """Normalize an artist key."""
    return " ".join(value.strip().split()).casefold()


def target_text(target: dict[str, Any], *keys: str) -> str:
    """Extract a non-secret text field from legacy target shapes."""
    candidates = [target]
    for nested in ("source", "metadata"):
        value = target.get(nested)
        if isinstance(value, dict):
            candidates.append(value)

    for candidate in candidates:
        for key in keys:
            value = candidate.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def apply_owner(
    engine: Engine,
    *,
    principal: AuthenticatedPrincipal,
    listings: set[tuple[str, str]],
    artists: list[dict[str, Any]],
    system_admin: bool,
) -> dict[str, Any]:
    """Apply the deterministic owner backfill in one transaction."""
    user_id = stable_user_id(principal)
    account_id = stable_personal_account_id(user_id)

    with engine.begin() as connection:
        if not relation_exists(connection, "identity.app_user"):
            raise RuntimeError("Phase-D D1 schema is not installed.")

        user_preexisting = bool(
            connection.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM identity.app_user
                        WHERE provider = :provider
                          AND subject = :subject
                    )
                    """
                ),
                {
                    "provider": principal.provider,
                    "subject": principal.subject,
                },
            ).scalar_one()
        )
        account_preexisting = bool(
            connection.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM identity.account
                        WHERE id = :account_id
                    )
                    """
                ),
                {"account_id": account_id},
            ).scalar_one()
        )

        connection.execute(
            text(
                """
                INSERT INTO identity.app_user (
                    id, provider, subject, email, display_name,
                    is_system_admin
                )
                VALUES (
                    :id, :provider, :subject, :email, :display_name,
                    :is_system_admin
                )
                ON CONFLICT (provider, subject)
                DO UPDATE SET
                    email = EXCLUDED.email,
                    display_name = EXCLUDED.display_name,
                    is_system_admin = (
                        identity.app_user.is_system_admin
                        OR EXCLUDED.is_system_admin
                    ),
                    updated_at = now()
                """
            ),
            {
                "id": user_id,
                "provider": principal.provider,
                "subject": principal.subject,
                "email": principal.email,
                "display_name": principal.display_name,
                "is_system_admin": system_admin,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO identity.account (id, name, account_type)
                VALUES (:id, :name, 'personal')
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": account_id,
                "name": f"{principal.display_name}'s Collector Ledger",
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO identity.account_member (
                    account_id, user_id, role
                )
                VALUES (:account_id, :user_id, 'owner')
                ON CONFLICT (account_id, user_id)
                DO UPDATE SET role = 'owner'
                """
            ),
            {"account_id": account_id, "user_id": user_id},
        )

        for marketplace, listing_id in sorted(listings):
            connection.execute(
                text(
                    """
                    INSERT INTO account.auction_listing (
                        account_id, marketplace, listing_id, source_kind
                    )
                    VALUES (
                        :account_id, :marketplace, :listing_id,
                        'owner-backfill'
                    )
                    ON CONFLICT (
                        account_id, marketplace, listing_id
                    )
                    DO NOTHING
                    """
                ),
                {
                    "account_id": account_id,
                    "marketplace": marketplace,
                    "listing_id": listing_id,
                },
            )

        enabled_searches = 0
        artist_count = 0
        for artist in artists:
            name = str(artist.get("name", "")).strip()
            if not name:
                continue
            normalized = normalize_name(name)
            artist_id = uuid.uuid5(
                account_id,
                f"tracked-artist:{normalized}",
            )
            connection.execute(
                text(
                    """
                    INSERT INTO account.tracked_artist (
                        id, account_id, name, normalized_name,
                        enabled, legacy_payload
                    )
                    VALUES (
                        :id, :account_id, :name, :normalized_name,
                        :enabled, CAST(:payload AS jsonb)
                    )
                    ON CONFLICT (account_id, normalized_name)
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        enabled = EXCLUDED.enabled,
                        legacy_payload = EXCLUDED.legacy_payload,
                        updated_at = now()
                    """
                ),
                {
                    "id": artist_id,
                    "account_id": account_id,
                    "name": name,
                    "normalized_name": normalized,
                    "enabled": bool(artist.get("enabled", True)),
                    "payload": json.dumps(artist, ensure_ascii=False),
                },
            )
            artist_count += 1

            targets = artist.get("targets", {})
            if not isinstance(targets, dict):
                continue

            for marketplace, target in targets.items():
                if marketplace not in {"ebay", "gripsweat"}:
                    continue
                if not isinstance(target, dict):
                    continue
                enabled = bool(target.get("enabled", False))
                connection.execute(
                    text(
                        """
                        INSERT INTO account.artist_marketplace (
                            tracked_artist_id,
                            marketplace,
                            enabled,
                            search_query,
                            search_url,
                            config_json
                        )
                        VALUES (
                            :artist_id,
                            :marketplace,
                            :enabled,
                            :search_query,
                            :search_url,
                            CAST(:config_json AS jsonb)
                        )
                        ON CONFLICT (
                            tracked_artist_id, marketplace
                        )
                        DO UPDATE SET
                            enabled = EXCLUDED.enabled,
                            search_query = EXCLUDED.search_query,
                            search_url = EXCLUDED.search_url,
                            config_json = EXCLUDED.config_json,
                            updated_at = now()
                        """
                    ),
                    {
                        "artist_id": artist_id,
                        "marketplace": marketplace,
                        "enabled": enabled,
                        "search_query": target_text(
                            target,
                            "search_query",
                            "query",
                            "keyword",
                            "search",
                        ),
                        "search_url": target_text(
                            target,
                            "search_url",
                            "url",
                            "url_template",
                        ),
                        "config_json": json.dumps(
                            target,
                            ensure_ascii=False,
                        ),
                    },
                )
                if enabled:
                    enabled_searches += 1

        legacy_updates: dict[str, int] = {}
        for relation in LEGACY_ACCOUNT_RELATIONS:
            if not should_backfill_account_relation(
                connection,
                relation,
            ):
                continue

            result = connection.execute(
                text(
                    f"""
                    UPDATE {relation}
                    SET account_id = :account_id
                    WHERE account_id IS NULL
                    """
                ),
                {"account_id": account_id},
            )
            legacy_updates[relation] = int(result.rowcount or 0)

        refresh_result = connection.execute(
            text(
                """
                UPDATE ops.refresh_job
                SET
                    account_id = COALESCE(account_id, :account_id),
                    requested_by_user_id = COALESCE(
                        requested_by_user_id,
                        :user_id
                    )
                WHERE account_id IS NULL
                   OR requested_by_user_id IS NULL
                """
            ),
            {"account_id": account_id, "user_id": user_id},
        )
        legacy_updates["ops.refresh_job"] = int(
            refresh_result.rowcount or 0
        )

    return {
        "user_id": str(user_id),
        "account_id": str(account_id),
        "user_preexisting": user_preexisting,
        "account_preexisting": account_preexisting,
        "listing_count": len(listings),
        "tracked_artist_count": artist_count,
        "marketplace_search_count": enabled_searches,
        "legacy_updates": legacy_updates,
    }


def parse_args() -> argparse.Namespace:
    """Parse owner migration arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument(
        "--expected-visible-listings",
        type=int,
        default=1441,
    )
    parser.add_argument(
        "--expected-tracked-artists",
        type=int,
        default=3,
    )
    parser.add_argument(
        "--expected-marketplace-searches",
        type=int,
        default=5,
    )
    parser.add_argument("--system-admin", action="store_true")
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> int:
    """Validate the owner workspace, then optionally backfill it."""
    args = parse_args()
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("ERROR: DATABASE_URL is required.")

    engine = create_engine(
        sqlalchemy_url(database_url),
        pool_pre_ping=True,
    )
    listings = current_listing_manifest(engine, database_url)
    artists, searches = current_artists()

    print(f"VISIBLE_LISTING_COUNT={len(listings)}")
    print(f"TRACKED_ARTIST_COUNT={len(artists)}")
    print(f"MARKETPLACE_SEARCH_COUNT={searches}")

    failures: list[str] = []
    if len(listings) != args.expected_visible_listings:
        failures.append(
            f"visible listings expected {args.expected_visible_listings}; "
            f"found {len(listings)}"
        )
    if len(artists) != args.expected_tracked_artists:
        failures.append(
            f"tracked artists expected {args.expected_tracked_artists}; "
            f"found {len(artists)}"
        )
    if searches != args.expected_marketplace_searches:
        failures.append(
            "marketplace searches expected "
            f"{args.expected_marketplace_searches}; found {searches}"
        )
    if failures:
        raise SystemExit(
            "ERROR: owner acceptance gate failed:\n"
            + "\n".join(failures)
        )

    if not args.apply:
        print("MODE=DRY_RUN")
        print("OWNER_BACKFILL_ACCEPTANCE_GATE=PASS")
        print("DATABASE_MUTATION_EXECUTED=false")
        return 0

    principal = AuthenticatedPrincipal(
        provider=args.provider,
        subject=args.subject,
        email=args.email,
        display_name=args.display_name,
    )
    result = apply_owner(
        engine,
        principal=principal,
        listings=listings,
        artists=artists,
        system_admin=args.system_admin,
    )

    evidence_root = (
        Path.home()
        / ".auction-etl"
        / "runtime"
        / "phase-d-account-overhaul"
    )
    evidence_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    evidence = evidence_root / f"owner-backfill-{stamp}.json"
    evidence.write_text(
        json.dumps(
            {
                "classification": "PHASE_D_OWNER_BACKFILL_APPLIED",
                "applied_at": datetime.now(timezone.utc).isoformat(),
                "provider": args.provider,
                "email": args.email,
                **result,
                "canonical_auction_rows_deleted": False,
                "controlled_v3_rerun": False,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("MODE=APPLY")
    print("OWNER_BACKFILL_APPLIED=true")
    print(f"OWNER_ACCOUNT_ID={result['account_id']}")
    print(f"OWNER_USER_ID={result['user_id']}")
    print(f"EVIDENCE={evidence}")
    print("CANONICAL_AUCTION_ROWS_DELETED=false")
    print("CONTROLLED_V3_RERUN_EXECUTED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
