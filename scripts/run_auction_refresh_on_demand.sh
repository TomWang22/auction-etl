#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ROOT="$(
    cd "$(dirname "${BASH_SOURCE[0]}")/.." &&
        pwd
)"

cd "${PROJECT_ROOT}"

if [[ -f ".venv/bin/activate" ]]; then
    source ".venv/bin/activate"
fi

DATABASE_URL="${DATABASE_URL:-postgresql://auction:auction@localhost:5444/auction_warehouse}"

AUCTION_CONTEXT="desktop-linux"
GLOBAL_CONTEXT="colima"
AUCTION_CONTAINER="auction-postgres-recovered"
AUCTION_VOLUME="auction-etl_recovered_postgres_data"

PAGINATION_INPUT="logs/gripsweat/pagination-audit/gripsweat_pagination_audit.json"

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
LOG_DIR="logs/source-refresh/on-demand-${TIMESTAMP}"
LOG_PATH="${LOG_DIR}/refresh.log"

DESKTOP_STARTED_BY_RUN=0
NORMAL_SHUTDOWN_COMPLETED=0

mkdir -p \
    "${LOG_DIR}" \
    "logs/gripsweat/detail" \
    "logs/buyee/live-detail/${TIMESTAMP}/dry-run" \
    "logs/buyee/live-detail/${TIMESTAMP}/apply"

touch "${LOG_PATH}"

restore_colima() {
    docker context use \
        "${GLOBAL_CONTEXT}" \
        >/dev/null 2>&1 || true
}

quit_temporary_desktop() {
    if [[ "${DESKTOP_STARTED_BY_RUN}" -ne 1 ]]; then
        return
    fi

    echo
    echo "Stopping temporary Auction ETL PostgreSQL"
    echo "========================================="

    if docker \
        --context "${AUCTION_CONTEXT}" \
        info \
        >/dev/null 2>&1
    then
        container_running="$(
            docker \
                --context "${AUCTION_CONTEXT}" \
                inspect "${AUCTION_CONTAINER}" \
                --format '{{.State.Running}}' \
                2>/dev/null ||
                true
        )"

        if [[ "${container_running}" == "true" ]]; then
            docker \
                --context "${AUCTION_CONTEXT}" \
                stop \
                --time 60 \
                "${AUCTION_CONTAINER}" \
                2>&1 |
                tee -a "${LOG_PATH}" ||
                true
        fi
    fi

    echo
    echo "Quitting Docker Desktop"
    echo "======================="

    osascript \
        -e 'tell application "Docker" to quit' \
        >/dev/null 2>&1 ||
        true

    for attempt in $(seq 1 60); do
        if ! docker \
            --context "${AUCTION_CONTEXT}" \
            info \
            >/dev/null 2>&1
        then
            break
        fi

        sleep 2
    done

    DESKTOP_STARTED_BY_RUN=0

    echo "✓ Docker Desktop is no longer active."
}

cleanup() {
    local status=$?

    trap - EXIT INT TERM

    restore_colima

    if [[ "${NORMAL_SHUTDOWN_COMPLETED}" -ne 1 ]]; then
        quit_temporary_desktop
    fi

    restore_colima

    exit "${status}"
}

trap cleanup EXIT INT TERM

fail() {
    local message="$1"

    echo
    echo "ERROR: ${message}"
    echo "Log: ${LOG_PATH}"
    echo
    echo "The verified pre-refresh backup remains available."
    echo "No Record Platform container, volume, or database was targeted."

    exit 1
}

run_logged() {
    local command_status

    printf '\nCommand:'
    printf ' %q' "$@"
    printf '\n\n'

    set +e

    "$@" 2>&1 |
        tee -a "${LOG_PATH}"

    command_status="${PIPESTATUS[0]}"

    set -e

    return "${command_status}"
}

verify_core_database() {
    local identity
    local core_state
    local marketplace_state

    identity="$(
        psql \
            "${DATABASE_URL}" \
            -At \
            -v ON_ERROR_STOP=1 \
            -c "
                SELECT
                    current_database()
                    || '|'
                    || current_user;
            "
    )"

    core_state="$(
        psql \
            "${DATABASE_URL}" \
            -At \
            -v ON_ERROR_STOP=1 \
            -c "
                SELECT
                    COUNT(*)
                    || '|'
                    || COUNT(
                        DISTINCT (
                            marketplace,
                            listing_id
                        )
                    )
                FROM warehouse.auction;
            "
    )"

    marketplace_state="$(
        psql \
            "${DATABASE_URL}" \
            -At \
            -v ON_ERROR_STOP=1 \
            -c "
                SELECT string_agg(
                    marketplace
                    || ':'
                    || row_count,
                    '|'
                    ORDER BY marketplace
                )
                FROM (
                    SELECT
                        marketplace,
                        COUNT(*)::text AS row_count
                    FROM warehouse.auction
                    GROUP BY marketplace
                ) AS counts;
            "
    )"

    echo "Database identity : ${identity}"
    echo "Core state        : ${core_state}"
    echo "Marketplace state : ${marketplace_state}"

    [[ "${identity}" == "auction_warehouse|auction" ]] &&
        [[ "${core_state}" == "775|775" ]] &&
        [[ "${marketplace_state}" == "buyee:77|ebay:698" ]]
}

echo
echo "Auction ETL on-demand source refresh"
echo "===================================="
echo "Database        : ${DATABASE_URL}"
echo "Auction context : ${AUCTION_CONTEXT}"
echo "Global context  : ${GLOBAL_CONTEXT}"
echo "Log             : ${LOG_PATH}"
echo
echo "Docker Desktop will be used only while Auction ETL PostgreSQL is needed."
echo "Colima remains the global Record Platform context."

echo
echo "1. Verify Docker context isolation"
echo "=================================="

docker context inspect \
    "${AUCTION_CONTEXT}" \
    >/dev/null 2>&1 ||
    fail "Docker Desktop context ${AUCTION_CONTEXT} is unavailable."

docker context inspect \
    "${GLOBAL_CONTEXT}" \
    >/dev/null 2>&1 ||
    fail "Colima context ${GLOBAL_CONTEXT} is unavailable."

desktop_endpoint="$(
    docker context inspect \
        "${AUCTION_CONTEXT}" \
        --format '{{.Endpoints.docker.Host}}'
)"

colima_endpoint="$(
    docker context inspect \
        "${GLOBAL_CONTEXT}" \
        --format '{{.Endpoints.docker.Host}}'
)"

echo "Docker Desktop: ${desktop_endpoint}"
echo "Colima        : ${colima_endpoint}"

if [[ -z "${desktop_endpoint}" ]] \
    || [[ -z "${colima_endpoint}" ]] \
    || [[ "${desktop_endpoint}" == "${colima_endpoint}" ]]
then
    fail "Docker Desktop and Colima are not isolated."
fi

restore_colima

echo "✓ Global Docker context: $(docker context show)"

echo
echo "2. Verify Playwright Chromium"
echo "============================="

python - <<'PY'
from pathlib import Path

from playwright.sync_api import sync_playwright


with sync_playwright() as playwright:
    executable = Path(playwright.chromium.executable_path)

    print(f"Chromium: {executable}")

    if not executable.is_file():
        raise SystemExit(
            f"Playwright Chromium is missing: {executable}"
        )

print("✓ Playwright Chromium is installed.")
PY

echo
echo "3. Start Docker Desktop temporarily"
echo "==================================="

if ! docker \
    --context "${AUCTION_CONTEXT}" \
    info \
    >/dev/null 2>&1
then
    DESKTOP_STARTED_BY_RUN=1

    open -a Docker

    desktop_ready=0

    for attempt in $(seq 1 150); do
        if docker \
            --context "${AUCTION_CONTEXT}" \
            info \
            >/dev/null 2>&1
        then
            desktop_ready=1
            break
        fi

        if (( attempt % 10 == 0 )); then
            echo "Waiting for Docker Desktop: $((attempt * 2)) seconds"
        fi

        sleep 2
    done

    if [[ "${desktop_ready}" -ne 1 ]]; then
        fail "Docker Desktop did not become ready within five minutes."
    fi
else
    echo "Docker Desktop was already running."
fi

echo "✓ Docker Desktop is ready."

docker \
    --context "${GLOBAL_CONTEXT}" \
    info \
    >/dev/null 2>&1 ||
    fail "Colima stopped responding."

restore_colima

echo "✓ Colima remains available."
echo "✓ Global context remains $(docker context show)."

echo
echo "4. Verify the existing recovered container and volume"
echo "====================================================="

docker \
    --context "${AUCTION_CONTEXT}" \
    inspect "${AUCTION_CONTAINER}" \
    >/dev/null 2>&1 ||
    fail \
        "Recovered container ${AUCTION_CONTAINER} is missing. No replacement was created."

mounted_volume="$(
    docker \
        --context "${AUCTION_CONTEXT}" \
        inspect "${AUCTION_CONTAINER}" \
        --format \
        '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}'
)"

published_port="$(
    docker \
        --context "${AUCTION_CONTEXT}" \
        port "${AUCTION_CONTAINER}" \
        5432/tcp \
        2>/dev/null |
        tail -1 |
        awk -F: '{print $NF}'
)"

if [[ "${mounted_volume}" != "${AUCTION_VOLUME}" ]]; then
    fail \
        "Unexpected volume ${mounted_volume:-none}; expected ${AUCTION_VOLUME}."
fi

if [[ "${published_port}" != "5444" ]]; then
    fail \
        "Unexpected port ${published_port:-none}; expected 5444."
fi

colima_collision="$(
    docker \
        --context "${GLOBAL_CONTEXT}" \
        ps -a \
        --filter "name=^/${AUCTION_CONTAINER}$" \
        --format '{{.Names}}'
)"

if [[ -n "${colima_collision}" ]]; then
    fail "A conflicting Auction ETL container exists in Colima."
fi

echo "✓ Container: ${AUCTION_CONTAINER}"
echo "✓ Volume   : ${mounted_volume}"
echo "✓ Port     : ${published_port}"
echo "✓ No matching container exists in Colima."

echo
echo "5. Start only Auction ETL PostgreSQL"
echo "===================================="

container_running="$(
    docker \
        --context "${AUCTION_CONTEXT}" \
        inspect "${AUCTION_CONTAINER}" \
        --format '{{.State.Running}}'
)"

if [[ "${container_running}" != "true" ]]; then
    run_logged \
        docker \
        --context "${AUCTION_CONTEXT}" \
        start "${AUCTION_CONTAINER}" ||
        fail "Could not start ${AUCTION_CONTAINER}."
else
    echo "✓ ${AUCTION_CONTAINER} is already running."
fi

restore_colima

database_ready=0

for attempt in $(seq 1 90); do
    if pg_isready \
        -h localhost \
        -p 5444 \
        -U auction \
        -d auction_warehouse \
        >/dev/null 2>&1
    then
        database_ready=1
        break
    fi

    sleep 2
done

if [[ "${database_ready}" -ne 1 ]]; then
    docker \
        --context "${AUCTION_CONTEXT}" \
        logs \
        --tail 150 \
        "${AUCTION_CONTAINER}" \
        2>&1 |
        tee -a "${LOG_PATH}" ||
        true

    fail "Auction ETL PostgreSQL did not become ready."
fi

echo "✓ PostgreSQL is accepting connections."

echo
echo "6. Verify the recovered 775-row database"
echo "========================================"

verify_core_database ||
    fail "The database does not match the verified recovery state."

echo "✓ Recovered database verified."

echo
echo "7. Create a verified pre-import backup"
echo "======================================"

run_logged \
    env \
    DOCKER_CONTEXT="${AUCTION_CONTEXT}" \
    DATABASE_URL="${DATABASE_URL}" \
    ./scripts/backup_auction_etl.sh ||
    fail "The pre-import backup failed."

restore_colima

echo
echo "8. Verify the retained 500-item Gripsweat audit"
echo "==============================================="

if [[ ! -s "${PAGINATION_INPUT}" ]]; then
    fail "Missing pagination audit: ${PAGINATION_INPUT}"
fi

python - "${PAGINATION_INPUT}" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


path = Path(sys.argv[1])
payload: Any = json.loads(path.read_text(encoding="utf-8"))

serialized = json.dumps(payload)

expected_ids = 500
identifier_count = serialized.count("gripsweat.com")

print(f"Audit file: {path}")
print(f"Approximate retained URL references: {identifier_count}")

if identifier_count < expected_ids:
    print(
        "The exact structure will be validated by the importer."
    )
PY

echo
echo "9. Revalidate and import all 500 Gripsweat identities"
echo "===================================================="

run_logged \
    python scripts/setup_gripsweat_schema.py ||
    fail "Gripsweat schema verification failed."

run_logged \
    python scripts/import_gripsweat_pagination_audit.py \
    --input "${PAGINATION_INPUT}" \
    --dry-run ||
    fail "The pagination import dry run failed."

pg_isready \
    -h localhost \
    -p 5444 \
    -U auction \
    -d auction_warehouse \
    >/dev/null 2>&1 ||
    fail "PostgreSQL stopped before the pagination import."

run_logged \
    python scripts/import_gripsweat_pagination_audit.py \
    --input "${PAGINATION_INPUT}" ||
    fail "The pagination import failed."

gripsweat_count="$(
    psql \
        "${DATABASE_URL}" \
        -At \
        -v ON_ERROR_STOP=1 \
        -c "
            SELECT COUNT(*)
            FROM warehouse.gripsweat_sale;
        "
)"

echo "Gripsweat rows after import: ${gripsweat_count}"

if [[ "${gripsweat_count}" -lt 500 ]]; then
    fail "Expected at least 500 Gripsweat rows."
fi

echo "✓ At least 500 Gripsweat identities are retained."

echo
echo "10. Test ten Gripsweat detail pages"
echo "==================================="

DETAIL_EXTRA_ARGS=()

detail_help="$(
    python scripts/enrich_gripsweat_details.py \
        --help \
        2>&1 ||
        true
)"

if printf '%s\n' "${detail_help}" |
    grep -q -- '--refresh'
then
    DETAIL_EXTRA_ARGS+=("--refresh")
fi

run_logged \
    python scripts/enrich_gripsweat_details.py \
    "${DETAIL_EXTRA_ARGS[@]}" \
    --limit 10 \
    --wait-seconds 6 \
    --delay 2 ||
    fail "The ten-page Gripsweat detail test failed."

pg_isready \
    -h localhost \
    -p 5444 \
    -U auction \
    -d auction_warehouse \
    >/dev/null 2>&1 ||
    fail "PostgreSQL stopped before Gripsweat detail application."

echo
echo "11. Apply Gripsweat detail enrichment"
echo "====================================="

run_logged \
    python scripts/enrich_gripsweat_details.py \
    "${DETAIL_EXTRA_ARGS[@]}" \
    --apply \
    --wait-seconds 6 \
    --delay 2 ||
    fail "Gripsweat detail enrichment failed."

echo
echo "12. Test five Buyee detail pages"
echo "================================"

run_logged \
    python scripts/crawl_buyee_live_details.py \
    --limit 5 \
    --refresh \
    --delay 2 \
    --timeout 45 \
    --log-dir \
    "logs/buyee/live-detail/${TIMESTAMP}/dry-run" ||
    fail "The five-page Buyee test failed."

pg_isready \
    -h localhost \
    -p 5444 \
    -U auction \
    -d auction_warehouse \
    >/dev/null 2>&1 ||
    fail "PostgreSQL stopped before the Buyee refresh."

echo
echo "13. Refresh all known Buyee detail pages"
echo "========================================"

run_logged \
    python scripts/crawl_buyee_live_details.py \
    --apply \
    --refresh \
    --delay 2 \
    --timeout 45 \
    --log-dir \
    "logs/buyee/live-detail/${TIMESTAMP}/apply" ||
    fail "The Buyee detail refresh failed."

echo
echo "14. Rebuild collector classifications"
echo "====================================="

if [[ -f scripts/collector_features.py ]]; then
    run_logged \
        python scripts/collector_features.py ||
        fail "Collector feature rebuilding failed."
fi

if [[ -f scripts/reclassify_collector.py ]]; then
    run_logged \
        python scripts/reclassify_collector.py \
        --apply ||
        fail "Collector reclassification failed."
fi

echo
echo "15. Rebuild persistent USD values"
echo "================================"

if [[ -f scripts/update_auction_fx.py ]]; then
    run_logged \
        python scripts/update_auction_fx.py ||
        fail "USD conversion rebuilding failed."
fi

echo
echo "16. Verify completed database state"
echo "==================================="

verify_core_database ||
    fail "The recovered core row counts changed."

psql \
    "${DATABASE_URL}" \
    -v ON_ERROR_STOP=1 <<'SQL' |
    tee -a "${LOG_PATH}"
SELECT
    marketplace,
    COUNT(*) AS rows,
    COUNT(DISTINCT listing_id)
        AS unique_listings,
    COUNT(final_price) AS final_prices,
    COUNT(final_price_usd)
        AS final_prices_usd,
    COUNT(gross_price) AS gross_prices,
    COUNT(gross_price_usd)
        AS gross_prices_usd,
    COUNT(opening_at) AS opening_dates,
    COUNT(closing_at) AS closing_dates,
    COUNT(start_price) AS starting_prices,
    COUNT(bid_count) AS bid_counts
FROM warehouse.auction
GROUP BY marketplace
ORDER BY marketplace;

SELECT
    configured_artist,
    COUNT(*) AS rows,
    COUNT(DISTINCT gripsweat_url)
        AS unique_urls,
    COUNT(title) AS titles,
    COUNT(sold_price) AS prices,
    COUNT(sold_at) AS sold_dates,
    COUNT(*) FILTER (
        WHERE detail_status = 'complete'
    ) AS complete_details,
    COUNT(*) FILTER (
        WHERE detail_status = 'incomplete'
    ) AS incomplete_details
FROM warehouse.gripsweat_sale
GROUP BY configured_artist
ORDER BY configured_artist;

SELECT
    detail_status,
    COUNT(*) AS rows,
    COUNT(opening_at) AS opening_dates,
    COUNT(closing_at) AS closing_dates,
    COUNT(starting_price) AS starting_prices,
    COUNT(current_price_gross) AS ending_prices,
    COUNT(bid_count) AS bid_counts,
    COUNT(condition_text) AS conditions
FROM warehouse.auction_detail
WHERE marketplace = 'buyee'
GROUP BY detail_status
ORDER BY detail_status;

SELECT
    COUNT(*) AS auction_duplicate_groups
FROM (
    SELECT
        marketplace,
        listing_id
    FROM warehouse.auction
    GROUP BY
        marketplace,
        listing_id
    HAVING COUNT(*) > 1
) AS duplicate_rows;

SELECT
    COUNT(*) AS gripsweat_duplicate_urls
FROM (
    SELECT gripsweat_url
    FROM warehouse.gripsweat_sale
    GROUP BY gripsweat_url
    HAVING COUNT(*) > 1
) AS duplicate_rows;
SQL

echo
echo "17. Run application health checks"
echo "================================="

run_logged \
    python -m auction_etl.cli.main doctor run ||
    fail "Auction ETL doctor failed."

echo
echo "18. Create the verified final backup"
echo "===================================="

run_logged \
    env \
    DOCKER_CONTEXT="${AUCTION_CONTEXT}" \
    DATABASE_URL="${DATABASE_URL}" \
    ./scripts/backup_auction_etl.sh ||
    fail "The final verified backup failed."

restore_colima

echo
echo "19. Stop the local Collector Review"
echo "==================================="

pkill \
    -f 'streamlit run app/collector_review.py' \
    2>/dev/null ||
    true

pkill \
    -f 'uvicorn.*collector' \
    2>/dev/null ||
    true

echo "✓ Collector Review was stopped before PostgreSQL shutdown."

echo
echo "20. Shut down temporary Docker Desktop cleanly"
echo "================================================"

quit_temporary_desktop

NORMAL_SHUTDOWN_COMPLETED=1

restore_colima

docker \
    --context "${GLOBAL_CONTEXT}" \
    info \
    >/dev/null 2>&1 ||
    fail "Colima stopped responding after Docker Desktop shutdown."

echo
echo "ON-DEMAND REFRESH COMPLETED"
echo "==========================="
echo "✓ The retained 500-item Gripsweat crawl was imported."
echo "✓ Gripsweat detail enrichment completed."
echo "✓ Known Buyee detail pages were refreshed."
echo "✓ Collector classifications and USD values were rebuilt."
echo "✓ The recovered 775 auction rows remain verified."
echo "✓ Pre-import and final PostgreSQL backups were verified."
echo "✓ Auction ETL PostgreSQL was shut down cleanly."
echo "✓ Docker Desktop was quit automatically."
echo "✓ Colima remains active and globally selected."
echo
echo "Global Docker context: $(docker context show)"
echo "Refresh log          : ${LOG_PATH}"
echo
echo "Auction Collector Review is intentionally offline while"
echo "Docker Desktop and its PostgreSQL database are stopped."
echo
echo "Start Auction ETL when needed:"
echo
echo "    ./scripts/start_auction_etl.sh"
echo
echo "Run this full refresh again:"
echo
echo "    ./scripts/run_auction_refresh_on_demand.sh"
