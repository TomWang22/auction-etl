"""Inspect or apply evidence-backed collector proposals."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from sqlalchemy import create_engine

from auction_etl.services.collector_evidence import (
    DEFAULT_CLOSING_WINDOW_MINUTES,
    DEFAULT_MINIMUM_COMPARABLES,
    apply_evidence_report,
    build_evidence_report,
)


def serialize(value: Any) -> str:
    """Serialize database-oriented scalar values."""
    return str(value)


def main() -> int:
    """Run the evidence assistant."""
    parser = argparse.ArgumentParser(
        description=(
            "Propose conservative condition, historical-anchor, "
            "and closing-window evidence."
        )
    )

    parser.add_argument("marketplace")
    parser.add_argument("listing_id")

    parser.add_argument(
        "--price-basis",
        choices=("HAMMER", "GROSS", "LANDED"),
        default="GROSS",
    )

    parser.add_argument(
        "--min-comparables",
        type=int,
        default=DEFAULT_MINIMUM_COMPARABLES,
    )

    parser.add_argument(
        "--closing-window-minutes",
        type=int,
        default=DEFAULT_CLOSING_WINDOW_MINUTES,
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Atomically apply only proposals with sufficient "
            "database evidence."
        ),
    )

    arguments = parser.parse_args()

    database_url = os.environ.get(
        "DATABASE_URL"
    )

    if not database_url:
        parser.error(
            "DATABASE_URL is not set."
        )

    engine = create_engine(
        database_url,
        pool_pre_ping=True,
    )

    report = build_evidence_report(
        engine,
        arguments.marketplace,
        arguments.listing_id,
        price_basis=arguments.price_basis,
        minimum_comparables=(
            arguments.min_comparables
        ),
        closing_window_minutes=(
            arguments.closing_window_minutes
        ),
    )

    applied_actions: tuple[str, ...] = tuple()

    if arguments.apply:
        applied_actions = apply_evidence_report(
            engine,
            report,
        )

    payload = {
        "report": report.to_dict(),
        "apply_requested": arguments.apply,
        "applied_actions": list(
            applied_actions
        ),
    }

    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=serialize,
        )
    )

    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
