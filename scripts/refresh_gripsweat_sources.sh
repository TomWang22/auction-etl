#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(
    cd "$(dirname "${BASH_SOURCE[0]}")" &&
        pwd
)"

PROJECT_ROOT="$(
    cd "${SCRIPT_DIR}/.." &&
        pwd
)"

cd "${PROJECT_ROOT}"

if [[ -f ".venv/bin/activate" ]]; then
    source .venv/bin/activate
fi

DATABASE_URL="${DATABASE_URL:-postgresql://auction:auction@localhost:5444/auction_warehouse}"
CONFIG_PATH="${GRIPSWEAT_CONFIG:-config/gripsweat_sources.json}"
PAGE_LIMIT="${GRIPSWEAT_PAGES:-10}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

RUN_DIR="logs/gripsweat/runs/${TIMESTAMP}"
RUN_LOG="${RUN_DIR}/refresh.log"
PRIVATE_RUN_DIR="${PROJECT_ROOT}/backups/private/gripsweat-runs/${TIMESTAMP}"

PERMANENT_SCRIPTS=(
    "scripts/probe_gripsweat.py"
    "scripts/setup_gripsweat_schema.py"
    "scripts/import_gripsweat_probe.py"
    "scripts/audit_gripsweat_pagination.py"
    "scripts/import_gripsweat_pagination_audit.py"
    "scripts/enrich_gripsweat_details.py"
)

fail() {
    local message="$1"

    echo
    echo "ERROR: ${message}"
    echo "Run log: ${RUN_LOG}"
    echo "No Record Platform resource was touched."

    exit 1
}

run_logged() {
    printf '\nCommand:'

    printf ' %q' "$@"

    printf '\n\n'

    "$@" 2>&1 |
        tee -a "${RUN_LOG}"
}

has_option() {
    local script_path="$1"
    local option="$2"
    local help_text

    help_text="$(
        python "${script_path}" --help 2>&1 ||
            true
    )"

    grep -Fq -- "${option}" <<< "${help_text}"
}

latest_json() {
    local directory="$1"
    local pattern="$2"

    find "${directory}" \
        -type f \
        -name "${pattern}" \
        -print \
        2>/dev/null |
        sort |
        tail -1
}

echo
echo "Auction ETL configured Gripsweat refresh"
echo "========================================"
echo "Database : ${DATABASE_URL}"
echo "Config   : ${CONFIG_PATH}"
echo "Pages    : ${PAGE_LIMIT} per enabled source"
echo
echo "No Record Platform container, database, or volume will be touched."

mkdir -p \
    "${PRIVATE_RUN_DIR}" \
    .git/info

grep -qxF '/backups/private/' \
    .git/info/exclude \
    2>/dev/null ||
    echo '/backups/private/' \
        >> .git/info/exclude

grep -qxF '/logs/gripsweat/' \
    .git/info/exclude \
    2>/dev/null ||
    echo '/logs/gripsweat/' \
        >> .git/info/exclude

echo
echo "1. Preserve previous Gripsweat diagnostics"
echo "=========================================="

if [[ -d "logs/gripsweat" ]] \
    && find logs/gripsweat \
        -type f \
        -print \
        -quit |
        grep -q .
then
    DIAGNOSTIC_ARCHIVE="${PRIVATE_RUN_DIR}/gripsweat-logs-before-${TIMESTAMP}.tar.gz"

    tar \
        -czf "${DIAGNOSTIC_ARCHIVE}" \
        logs/gripsweat

    chmod 600 "${DIAGNOSTIC_ARCHIVE}"

    echo "✓ Previous diagnostics: ${DIAGNOSTIC_ARCHIVE}"
else
    echo "No previous diagnostics required preservation."
fi

rm -rf \
    logs/gripsweat/probe \
    logs/gripsweat/html \
    logs/gripsweat/screenshots \
    logs/gripsweat/pagination-audit \
    logs/gripsweat/import \
    logs/gripsweat/detail

mkdir -p \
    "${RUN_DIR}" \
    logs/gripsweat/probe \
    logs/gripsweat/html \
    logs/gripsweat/screenshots \
    logs/gripsweat/pagination-audit \
    logs/gripsweat/import \
    logs/gripsweat/detail

touch "${RUN_LOG}"

echo
echo "2. Verify the isolated Auction ETL database"
echo "==========================================="

if [[ ! -x "scripts/ensure_auction_postgres.sh" ]]; then
    fail "scripts/ensure_auction_postgres.sh is missing."
fi

if ! run_logged \
    env DATABASE_URL="${DATABASE_URL}" \
    ./scripts/ensure_auction_postgres.sh
then
    fail "The isolated Auction ETL database is unavailable."
fi

database_identity="$(
    psql \
        "${DATABASE_URL}" \
        -v ON_ERROR_STOP=1 \
        -Atc "
            SELECT
                current_database()
                || '|'
                || current_user;
        "
)"

if [[ "${database_identity}" != "auction_warehouse|auction" ]]; then
    fail "Unexpected database identity: ${database_identity}"
fi

core_before="$(
    psql \
        "${DATABASE_URL}" \
        -v ON_ERROR_STOP=1 \
        -Atc "
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

if [[ "${core_before}" != "775|775" ]]; then
    fail "Expected 775 recovered auction rows; found ${core_before}."
fi

echo "✓ Database identity: ${database_identity}"
echo "✓ Core row state   : ${core_before}"

echo
echo "3. Create a verified pre-crawl backup"
echo "====================================="

if [[ ! -x "scripts/backup_auction_etl.sh" ]]; then
    fail "scripts/backup_auction_etl.sh is missing."
fi

if ! run_logged \
    env DATABASE_URL="${DATABASE_URL}" \
    ./scripts/backup_auction_etl.sh
then
    fail "The pre-crawl database backup failed."
fi

echo
echo "4. Compile permanent Gripsweat tooling"
echo "======================================"

if [[ ! -f "${CONFIG_PATH}" ]]; then
    fail "Configured source file is missing: ${CONFIG_PATH}"
fi

for script_path in "${PERMANENT_SCRIPTS[@]}"; do
    if [[ ! -f "${script_path}" ]]; then
        fail "Required script is missing: ${script_path}"
    fi

    chmod +x "${script_path}"
done

if ! run_logged \
    python -m py_compile \
    "${PERMANENT_SCRIPTS[@]}"
then
    fail "One or more Gripsweat scripts failed compilation."
fi

echo
echo "5. Verify enabled Gripsweat sources"
echo "==================================="

python - "${CONFIG_PATH}" 2>&1 <<'PY' | tee -a "${RUN_LOG}"
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import quote_plus


path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))

if not isinstance(payload, list):
    raise SystemExit(
        "Gripsweat configuration must contain a JSON list."
    )

enabled = [
    source
    for source in payload
    if isinstance(source, dict)
    and source.get("enabled", True)
]

if not enabled:
    raise SystemExit(
        "No enabled Gripsweat sources were found."
    )

print(f"Enabled sources: {len(enabled)}")
print()

for source in enabled:
    name = str(source["name"])
    artist = str(source["artist"])
    query = quote_plus(str(source["query"]))
    template = str(source["url_template"])

    page_one = template.format(
        query=query,
        page=1,
    )

    print(f"{name}: {artist}")
    print(f"  {page_one}")
PY

echo
echo "6. Run a fresh page-one probe"
echo "============================="

PROBE_SCRIPT="scripts/probe_gripsweat.py"
PROBE_OUTPUT="logs/gripsweat/probe/gripsweat_probe.json"

PROBE_COMMAND=(
    python
    "${PROBE_SCRIPT}"
)

if has_option "${PROBE_SCRIPT}" "--config"; then
    PROBE_COMMAND+=(
        --config
        "${CONFIG_PATH}"
    )
fi

if has_option "${PROBE_SCRIPT}" "--max-pages"; then
    PROBE_COMMAND+=(
        --max-pages
        1
    )
elif has_option "${PROBE_SCRIPT}" "--pages"; then
    PROBE_COMMAND+=(
        --pages
        1
    )
fi

if has_option "${PROBE_SCRIPT}" "--wait-seconds"; then
    PROBE_COMMAND+=(
        --wait-seconds
        8
    )
fi

if has_option "${PROBE_SCRIPT}" "--delay"; then
    PROBE_COMMAND+=(
        --delay
        2
    )
fi

if has_option "${PROBE_SCRIPT}" "--timeout"; then
    PROBE_COMMAND+=(
        --timeout
        45
    )
fi

if has_option "${PROBE_SCRIPT}" "--refresh"; then
    PROBE_COMMAND+=(
        --refresh
    )
fi

if has_option "${PROBE_SCRIPT}" "--output"; then
    PROBE_COMMAND+=(
        --output
        "${PROBE_OUTPUT}"
    )
fi

if has_option "${PROBE_SCRIPT}" "--diagnostic-dir"; then
    PROBE_COMMAND+=(
        --diagnostic-dir
        logs/gripsweat
    )
fi

if ! run_logged "${PROBE_COMMAND[@]}"; then
    fail "The fresh page-one Gripsweat probe failed."
fi

if [[ ! -s "${PROBE_OUTPUT}" ]]; then
    PROBE_OUTPUT="$(
        latest_json \
            logs/gripsweat \
            '*probe*.json'
    )"
fi

if [[ -z "${PROBE_OUTPUT}" ]] \
    || [[ ! -s "${PROBE_OUTPUT}" ]]
then
    fail "The probe did not create a readable JSON result."
fi

echo "✓ Probe result: ${PROBE_OUTPUT}"

core_after_probe="$(
    psql \
        "${DATABASE_URL}" \
        -v ON_ERROR_STOP=1 \
        -Atc "
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

if [[ "${core_after_probe}" != "${core_before}" ]]; then
    fail "The read-only probe changed core auction rows."
fi

echo "✓ Probe performed no core auction writes."

echo
echo "7. Verify the normalized Gripsweat schema"
echo "========================================="

if ! run_logged \
    python scripts/setup_gripsweat_schema.py
then
    fail "Gripsweat schema setup failed."
fi

echo
echo "8. Import the fresh page-one probe"
echo "=================================="

IMPORT_PROBE_SCRIPT="scripts/import_gripsweat_probe.py"

IMPORT_PROBE_COMMAND=(
    python
    "${IMPORT_PROBE_SCRIPT}"
)

if has_option "${IMPORT_PROBE_SCRIPT}" "--config"; then
    IMPORT_PROBE_COMMAND+=(
        --config
        "${CONFIG_PATH}"
    )
fi

if has_option "${IMPORT_PROBE_SCRIPT}" "--probe"; then
    IMPORT_PROBE_COMMAND+=(
        --probe
        "${PROBE_OUTPUT}"
    )
elif has_option "${IMPORT_PROBE_SCRIPT}" "--input"; then
    IMPORT_PROBE_COMMAND+=(
        --input
        "${PROBE_OUTPUT}"
    )
fi

if has_option "${IMPORT_PROBE_SCRIPT}" "--dry-run"; then
    if ! run_logged \
        "${IMPORT_PROBE_COMMAND[@]}" \
        --dry-run
    then
        fail "The probe import dry run failed."
    fi
fi

if has_option "${IMPORT_PROBE_SCRIPT}" "--apply"; then
    IMPORT_PROBE_COMMAND+=(
        --apply
    )
fi

if ! run_logged "${IMPORT_PROBE_COMMAND[@]}"; then
    fail "The probe import failed."
fi

echo
echo "9. Crawl ${PAGE_LIMIT} fresh pages per enabled source"
echo "====================================================="

AUDIT_SCRIPT="scripts/audit_gripsweat_pagination.py"

AUDIT_COMMAND=(
    python
    "${AUDIT_SCRIPT}"
)

if has_option "${AUDIT_SCRIPT}" "--config"; then
    AUDIT_COMMAND+=(
        --config
        "${CONFIG_PATH}"
    )
fi

if has_option "${AUDIT_SCRIPT}" "--pages"; then
    AUDIT_COMMAND+=(
        --pages
        "${PAGE_LIMIT}"
    )
elif has_option "${AUDIT_SCRIPT}" "--max-pages"; then
    AUDIT_COMMAND+=(
        --max-pages
        "${PAGE_LIMIT}"
    )
fi

if has_option "${AUDIT_SCRIPT}" "--wait-seconds"; then
    AUDIT_COMMAND+=(
        --wait-seconds
        6
    )
fi

if has_option "${AUDIT_SCRIPT}" "--delay"; then
    AUDIT_COMMAND+=(
        --delay
        2
    )
fi

if has_option "${AUDIT_SCRIPT}" "--timeout"; then
    AUDIT_COMMAND+=(
        --timeout
        45
    )
fi

if has_option "${AUDIT_SCRIPT}" "--empty-page-limit"; then
    AUDIT_COMMAND+=(
        --empty-page-limit
        2
    )
fi

if has_option "${AUDIT_SCRIPT}" "--refresh"; then
    AUDIT_COMMAND+=(
        --refresh
    )
fi

if ! run_logged "${AUDIT_COMMAND[@]}"; then
    fail "The fresh pagination crawl failed."
fi

PAGINATION_OUTPUT="$(
    latest_json \
        logs/gripsweat/pagination-audit \
        '*.json'
)"

if [[ -z "${PAGINATION_OUTPUT}" ]]; then
    PAGINATION_OUTPUT="$(
        latest_json \
            logs/gripsweat \
            '*pagination*audit*.json'
    )"
fi

if [[ -z "${PAGINATION_OUTPUT}" ]] \
    || [[ ! -s "${PAGINATION_OUTPUT}" ]]
then
    fail "The pagination crawl did not create a readable audit JSON file."
fi

echo "✓ Pagination audit: ${PAGINATION_OUTPUT}"

echo
echo "10. Validate and import the pagination crawl"
echo "============================================"

PAGINATION_IMPORT_SCRIPT="scripts/import_gripsweat_pagination_audit.py"

PAGINATION_IMPORT_COMMAND=(
    python
    "${PAGINATION_IMPORT_SCRIPT}"
)

if has_option "${PAGINATION_IMPORT_SCRIPT}" "--input"; then
    PAGINATION_IMPORT_COMMAND+=(
        --input
        "${PAGINATION_OUTPUT}"
    )
elif has_option "${PAGINATION_IMPORT_SCRIPT}" "--audit"; then
    PAGINATION_IMPORT_COMMAND+=(
        --audit
        "${PAGINATION_OUTPUT}"
    )
fi

if has_option "${PAGINATION_IMPORT_SCRIPT}" "--dry-run"; then
    if ! run_logged \
        "${PAGINATION_IMPORT_COMMAND[@]}" \
        --dry-run
    then
        fail "The pagination import dry run failed."
    fi
fi

if has_option "${PAGINATION_IMPORT_SCRIPT}" "--apply"; then
    PAGINATION_IMPORT_COMMAND+=(
        --apply
    )
fi

if ! run_logged "${PAGINATION_IMPORT_COMMAND[@]}"; then
    fail "The pagination import failed."
fi

echo
echo "11. Test ten Gripsweat detail pages without writes"
echo "=================================================="

DETAIL_SCRIPT="scripts/enrich_gripsweat_details.py"

DETAIL_DRY_COMMAND=(
    python
    "${DETAIL_SCRIPT}"
)

if has_option "${DETAIL_SCRIPT}" "--config"; then
    DETAIL_DRY_COMMAND+=(
        --config
        "${CONFIG_PATH}"
    )
fi

if has_option "${DETAIL_SCRIPT}" "--limit"; then
    DETAIL_DRY_COMMAND+=(
        --limit
        10
    )
else
    fail "The detail crawler does not expose the required --limit option."
fi

if has_option "${DETAIL_SCRIPT}" "--refresh"; then
    DETAIL_DRY_COMMAND+=(
        --refresh
    )
fi

if has_option "${DETAIL_SCRIPT}" "--wait-seconds"; then
    DETAIL_DRY_COMMAND+=(
        --wait-seconds
        6
    )
fi

if has_option "${DETAIL_SCRIPT}" "--delay"; then
    DETAIL_DRY_COMMAND+=(
        --delay
        2
    )
fi

if has_option "${DETAIL_SCRIPT}" "--timeout"; then
    DETAIL_DRY_COMMAND+=(
        --timeout
        45
    )
fi

if ! run_logged "${DETAIL_DRY_COMMAND[@]}"; then
    fail "The ten-page detail dry run failed."
fi

echo
echo "12. Apply fresh detail enrichment"
echo "================================="

if ! has_option "${DETAIL_SCRIPT}" "--apply"; then
    fail "The detail crawler does not expose the required --apply option."
fi

DETAIL_APPLY_COMMAND=(
    python
    "${DETAIL_SCRIPT}"
    --apply
)

if has_option "${DETAIL_SCRIPT}" "--config"; then
    DETAIL_APPLY_COMMAND+=(
        --config
        "${CONFIG_PATH}"
    )
fi

if has_option "${DETAIL_SCRIPT}" "--refresh"; then
    DETAIL_APPLY_COMMAND+=(
        --refresh
    )
fi

if has_option "${DETAIL_SCRIPT}" "--wait-seconds"; then
    DETAIL_APPLY_COMMAND+=(
        --wait-seconds
        6
    )
fi

if has_option "${DETAIL_SCRIPT}" "--delay"; then
    DETAIL_APPLY_COMMAND+=(
        --delay
        2
    )
fi

if has_option "${DETAIL_SCRIPT}" "--timeout"; then
    DETAIL_APPLY_COMMAND+=(
        --timeout
        45
    )
fi

echo "This can take several minutes."

if ! run_logged "${DETAIL_APPLY_COMMAND[@]}"; then
    fail "The Gripsweat detail enrichment failed."
fi

echo
echo "13. Verify Gripsweat coverage and deduplication"
echo "==============================================="

psql \
    "${DATABASE_URL}" \
    -v ON_ERROR_STOP=1 <<'SQL' |
    tee -a "${RUN_LOG}"
SELECT
    current_database() AS database_name,
    current_user AS database_user;

SELECT
    configured_artist,
    COUNT(*) AS rows,
    COUNT(DISTINCT gripsweat_url)
        AS unique_urls,
    COUNT(sold_price) AS priced_rows,
    COUNT(title) AS titled_rows,
    COUNT(sold_at) AS dated_rows,
    COUNT(image_url) AS image_rows,
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
    COUNT(*) AS total_rows,
    COUNT(DISTINCT gripsweat_url)
        AS unique_urls
FROM warehouse.gripsweat_sale;

SELECT
    COUNT(*) AS duplicate_source_item_groups
FROM (
    SELECT
        source_name,
        gripsweat_item_key
    FROM warehouse.gripsweat_sale
    GROUP BY
        source_name,
        gripsweat_item_key
    HAVING COUNT(*) > 1
) AS duplicates;

SELECT
    COUNT(*) AS duplicate_url_groups
FROM (
    SELECT gripsweat_url
    FROM warehouse.gripsweat_sale
    GROUP BY gripsweat_url
    HAVING COUNT(*) > 1
) AS duplicates;
SQL

source_count="$(
    psql \
        "${DATABASE_URL}" \
        -v ON_ERROR_STOP=1 \
        -Atc "
            SELECT COUNT(*)
            FROM warehouse.gripsweat_source;
        "
)"

sale_count="$(
    psql \
        "${DATABASE_URL}" \
        -v ON_ERROR_STOP=1 \
        -Atc "
            SELECT COUNT(*)
            FROM warehouse.gripsweat_sale;
        "
)"

duplicate_urls="$(
    psql \
        "${DATABASE_URL}" \
        -v ON_ERROR_STOP=1 \
        -Atc "
            SELECT COUNT(*)
            FROM (
                SELECT gripsweat_url
                FROM warehouse.gripsweat_sale
                GROUP BY gripsweat_url
                HAVING COUNT(*) > 1
            ) AS duplicates;
        "
)"

if [[ "${source_count}" -lt 2 ]]; then
    fail "Expected at least two Gripsweat sources; found ${source_count}."
fi

if [[ "${sale_count}" -lt 500 ]]; then
    fail "Expected at least 500 retained sales; found ${sale_count}."
fi

if [[ "${duplicate_urls}" -ne 0 ]]; then
    fail "Duplicate Gripsweat URL groups were detected: ${duplicate_urls}."
fi

core_after="$(
    psql \
        "${DATABASE_URL}" \
        -v ON_ERROR_STOP=1 \
        -Atc "
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

if [[ "${core_after}" != "${core_before}" ]]; then
    fail "The Gripsweat refresh changed the recovered core auction counts."
fi

echo "✓ Configured sources : ${source_count}"
echo "✓ Retained sales     : ${sale_count}"
echo "✓ Duplicate URLs     : ${duplicate_urls}"
echo "✓ Core auction state : ${core_after}"

echo
echo "14. Run Auction ETL health checks"
echo "================================="

if ! run_logged \
    python -m auction_etl.cli.main doctor run
then
    fail "Auction ETL doctor reported a failure."
fi

echo
echo "15. Create a verified post-crawl backup"
echo "======================================="

if ! run_logged \
    env DATABASE_URL="${DATABASE_URL}" \
    ./scripts/backup_auction_etl.sh
then
    fail "The post-crawl database backup failed."
fi

echo
echo "16. Restart only Auction ETL"
echo "============================"

if [[ -x "scripts/start_auction_etl.sh" ]]; then
    if ! run_logged \
        env DATABASE_URL="${DATABASE_URL}" \
        ./scripts/start_auction_etl.sh
    then
        fail "Auction ETL startup failed after the crawl."
    fi
else
    echo "WARNING: scripts/start_auction_etl.sh was not found."
fi

ui_ready=0

for attempt in $(seq 1 30); do
    if curl \
        --silent \
        --fail \
        http://127.0.0.1:8501 \
        >/dev/null 2>&1
    then
        ui_ready=1
        break
    fi

    sleep 1
done

if [[ "${ui_ready}" -eq 1 ]]; then
    echo "✓ Collector Review is responding."
    echo "URL: http://127.0.0.1:8501"
else
    echo "WARNING: the crawl succeeded, but the UI is not responding."
fi

echo
echo "Gripsweat refresh completed"
echo "==========================="
echo "Sources     : ${source_count}"
echo "Sales       : ${sale_count}"
echo "Pages/source: ${PAGE_LIMIT}"
echo "Probe       : ${PROBE_OUTPUT}"
echo "Pagination  : ${PAGINATION_OUTPUT}"
echo "Run log     : ${RUN_LOG}"
echo
echo "✓ Fresh search pages were crawled."
echo "✓ Pagination was validated before import."
echo "✓ Detail pages were tested before writes."
echo "✓ Detail enrichment was applied."
echo "✓ Core auction rows remained 775."
echo "✓ Pre-crawl and post-crawl backups were verified."
echo "✓ No Record Platform resource was touched."
