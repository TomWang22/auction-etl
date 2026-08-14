#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${HOME}/auction-etl"
CONFIG_FILE="${PROJECT_DIR}/config/ebay_sources.json"

cd "${PROJECT_DIR}"

mkdir -p \
    logs \
    reports/buyee \
    reports/ebay

started_at="$(
    date -u '+%Y-%m-%dT%H:%M:%SZ'
)"

handle_failure() {
    exit_code=$?

    echo
    echo "============================================================"
    echo "Auction ETL FAILED"
    echo "Started : ${started_at}"
    echo "Failed  : $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "Exit    : ${exit_code}"
    echo "Existing reports were preserved."
    echo "============================================================"

    exit "${exit_code}"
}

trap handle_failure ERR

echo
echo "============================================================"
echo "Auction ETL started: ${started_at}"
echo "============================================================"

uv sync --quiet

echo
echo "Running the canonical ingestion round:"
echo "  cron -> launch_latest_refresh_job.py -> guarded ingestion runner"
echo

set +e

uv run python scripts/launch_latest_refresh_job.py \
    --trigger cron

refresh_status="$?"

set -e

if [[ "${refresh_status}" -eq 2 ]]; then
    echo
    echo "Another ingestion round is already running."
    echo "The scheduled round will exit without overlap."
    exit 0
fi

if [[ "${refresh_status}" -ne 0 ]]; then
    echo
    echo "Canonical ingestion round failed with status ${refresh_status}." >&2
    exit "${refresh_status}"
fi

echo
echo "Canonical ingestion round completed."

if [[ "${AUCTION_REPORTS_REFRESH_ONLY:-0}" == "1" ]]; then
    echo "AUCTION_REPORTS_REFRESH_ONLY=1; report generation skipped."
    exit 0
fi

uv run python scripts/enrich_buyee_details.py \
    --profile anonymous \
    --wait-seconds 2

uv run python -m auction_etl.cli.main \
    report all \
    --marketplace buyee \
    --exclude-bulk \
    --all-statuses \
    --exclude-shipping \
    --output-dir reports/buyee \
    --title "Buyee Auctions — Stored 10% Tax"

uv run python - <<'PY'
from __future__ import annotations

import json
import subprocess
from pathlib import Path

sources = json.loads(
    Path(
        "config/ebay_sources.json"
    ).read_text(
        encoding="utf-8"
    )
)

for source in sources:
    if not source.get(
        "enabled",
        True,
    ):
        continue

    name = str(source["name"])
    seller = str(source["seller"])

    output_dir = (
        Path("reports/ebay")
        / name
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    command = [
        "uv",
        "run",
        "python",
        "-m",
        "auction_etl.cli.main",
        "report",
        "all",
        "--marketplace",
        "ebay",
        "--seller",
        seller,
        "--exclude-shipping",
        "--output-dir",
        str(output_dir),
        "--title",
        f"{name} — Completed eBay Auctions",
    ]

    command.append(
        "--exclude-bulk"
        if source.get(
            "exclude_bulk",
            True,
        )
        else "--include-bulk"
    )

    command.append(
        "--completed-only"
        if source.get(
            "completed_only",
            True,
        )
        else "--all-statuses"
    )

    if source.get(
        "apply_tax",
        True,
    ):
        command.extend(
            [
                "--apply-ebay-tax",
                "--ebay-tax-rate",
                str(
                    source.get(
                        "tax_rate",
                        0.0625,
                    )
                ),
            ]
        )
    else:
        command.append(
            "--no-ebay-tax"
        )

    subprocess.run(
        command,
        check=True,
    )
PY

uv run python -m auction_etl.cli.main \
    doctor run

echo
echo "Generated reports:"

find reports \
    -maxdepth 4 \
    -type f \
    \( \
        -name '*.csv' \
        -o -name '*.xlsx' \
        -o -name '*.docx' \
    \) \
    -exec ls -lh {} \;

echo
echo "Auction ETL finished: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
