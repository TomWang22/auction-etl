#!/usr/bin/env python3
"""Fail-closed static gate for Phase-D critical account-scoped runtime paths."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Contract:
    """One runtime source-account scoping contract."""

    path: str
    required_any: tuple[tuple[str, ...], ...]
    description: str


CONTRACTS = (
    Contract(
        "app/collector_review.py",
        (
            ("account.auction_listing",),
            ("account_id",),
            (
                "load_records(account_id",
                "load_records(\n    account_id",
                "load_records(\n        account_id",
            ),
            (
                "warehouse.auction_collector",
                "account_id",
            ),
        ),
        "Collector Review visibility, cache key, and private metadata",
    ),
    Contract(
        "app/pages/16_Artists_to_Track.py",
        (
            ("account_id", "AccountContext"),
            (
                "account.tracked_artist",
                "list_tracked_artists(",
            ),
        ),
        "Artists-to-Track account context",
    ),
    Contract(
        "auction_etl/services/artist_tracking.py",
        (
            ("account.tracked_artist",),
            ("account.artist_marketplace",),
            ("account_id",),
        ),
        "Tracked artists stored per account",
    ),
    Contract(
        "auction_etl/services/refresh_jobs.py",
        (
            ("account_id",),
            ("requested_by_user_id",),
            (
                "WHERE account_id",
                "account_id = :account_id",
                "job.account_id",
            ),
        ),
        "Durable refresh creation/reads are account-aware",
    ),
    Contract(
        "auction_etl/cloud_api.py",
        (
            ("account_id",),
            (
                "account_member",
                "require_account",
                "resolve_account",
                "membership",
            ),
        ),
        "Control plane does not trust an arbitrary account UUID",
    ),
    Contract(
        "scripts/run_cloud_refresh_worker.py",
        (
            ("account_id",),
            (
                "AUCTION_ACCOUNT_ID",
                "account_id",
            ),
        ),
        "Worker carries the claimed job account",
    ),
    Contract(
        "auction_etl/services/auction_intake.py",
        (
            ("account_id",),
            (
                "account.auction_listing",
                "account_id",
            ),
        ),
        "New-auction intake/private workflow state is account-aware",
    ),
    Contract(
        "app/pages/3_Latest_Auction_Refresh.py",
        (
            ("account_id", "AccountContext"),
        ),
        "Refresh UI derives current account",
    ),
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.home() / "auction-etl",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
    )
    return parser.parse_args()


def normalize(source: str) -> str:
    """Normalize whitespace enough for conservative source markers."""
    return re.sub(r"[ \t]+", " ", source)


def evaluate_contract(repo: Path, contract: Contract) -> dict[str, object]:
    """Evaluate one source contract without executing repository code."""
    path = repo / contract.path

    if not path.is_file():
        return {
            "path": contract.path,
            "description": contract.description,
            "pass": False,
            "missing": ["FILE_MISSING"],
        }

    source = normalize(path.read_text(encoding="utf-8", errors="replace"))
    missing: list[str] = []

    for alternatives in contract.required_any:
        if not any(marker in source for marker in alternatives):
            missing.append(" OR ".join(alternatives))

    return {
        "path": contract.path,
        "description": contract.description,
        "pass": not missing,
        "missing": missing,
    }


def main() -> int:
    """Run the strict source-account scoping gate."""
    args = parse_args()
    repo = args.repo.expanduser().resolve()

    if not (repo / ".git").exists():
        raise SystemExit(f"ERROR: not a Git checkout: {repo}")

    results = [
        evaluate_contract(repo, contract)
        for contract in CONTRACTS
    ]

    failed = [
        result
        for result in results
        if not bool(result["pass"])
    ]

    payload = {
        "contracts": results,
        "failed_count": len(failed),
        "pass": not failed,
        "safety": {
            "database_command_executed": False,
            "cloud_command_executed": False,
            "refresh_command_executed": False,
            "controlled_v3_rerun_executed": False,
        },
    }

    if args.json_output is not None:
        output = args.json_output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"JSON={output}")

    for result in results:
        status = "PASS" if result["pass"] else "FAIL"
        print(f"{status} {result['path']}")
        for marker in result["missing"]:
            print(f"  MISSING={marker}")

    print(f"CRITICAL_RUNTIME_CONTRACTS={len(results)}")
    print(f"CRITICAL_RUNTIME_FAILURES={len(failed)}")
    print(
        "MIGRATION_GATE_PASS="
        + ("true" if not failed else "false")
    )
    print("DATABASE_MUTATION_EXECUTED=false")
    print("CLOUD_MUTATION_EXECUTED=false")
    print("CONTROLLED_V3_RERUN_EXECUTED=false")

    return 0 if not failed else 3


if __name__ == "__main__":
    raise SystemExit(main())
