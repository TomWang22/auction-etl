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

GRIPSWEAT_REFRESH="scripts/refresh_gripsweat_sources.sh"
BUYEE_CRAWLER="scripts/crawl_buyee_live_details.py"

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
LOG_DIR="logs/source-refresh/${TIMESTAMP}"
LOG_PATH="${LOG_DIR}/refresh.log"
PRIVATE_SCRIPT_BACKUP="backups/private/script-snapshots/${TIMESTAMP}"

mkdir -p \
    "${LOG_DIR}" \
    "${PRIVATE_SCRIPT_BACKUP}" \
    "logs/buyee/live-detail/${TIMESTAMP}/dry-run" \
    "logs/buyee/live-detail/${TIMESTAMP}/apply"

touch "${LOG_PATH}"

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

restore_colima() {
    docker context use \
        "${GLOBAL_CONTEXT}" \
        >/dev/null 2>&1 || true
}

fail() {
    local message="$1"

    echo
    echo "ERROR: ${message}"
    echo "Log: ${LOG_PATH}"
    echo
    echo "No explicit Docker command targeted a Record Platform resource."

    restore_colima

    exit 1
}

verify_database() {
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

trap restore_colima EXIT

echo
echo "Auction ETL isolated source refresh"
echo "==================================="
echo "Database        : ${DATABASE_URL}"
echo "Auction context : ${AUCTION_CONTEXT}"
echo "Global context  : ${GLOBAL_CONTEXT}"
echo "Log             : ${LOG_PATH}"
echo
echo "Docker Desktop may start stale containers because of their existing"
echo "restart policies. This workflow never targets those containers."

echo
echo "1. Verify the two Docker contexts"
echo "================================="

docker context inspect \
    "${AUCTION_CONTEXT}" \
    >/dev/null 2>&1 ||
    fail "Docker context ${AUCTION_CONTEXT} does not exist."

docker context inspect \
    "${GLOBAL_CONTEXT}" \
    >/dev/null 2>&1 ||
    fail "Docker context ${GLOBAL_CONTEXT} does not exist."

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
    fail "The Docker contexts do not resolve to separate daemons."
fi

restore_colima

echo "✓ Global context: $(docker context show)"

echo
echo "2. Start Docker Desktop without stopping Colima"
echo "================================================"

if ! docker \
    --context "${AUCTION_CONTEXT}" \
    info \
    >/dev/null 2>&1
then
    echo "Starting Docker Desktop..."

    open -a Docker

    desktop_ready=0

    for attempt in $(seq 1 90); do
        if docker \
            --context "${AUCTION_CONTEXT}" \
            info \
            >/dev/null 2>&1
        then
            desktop_ready=1
            break
        fi

        sleep 2
    done

    if [[ "${desktop_ready}" -ne 1 ]]; then
        fail "Docker Desktop did not become ready."
    fi
fi

docker \
    --context "${GLOBAL_CONTEXT}" \
    info \
    >/dev/null 2>&1 ||
    fail "Colima is not responding."

restore_colima

echo "✓ Docker Desktop is available."
echo "✓ Colima remains available."
echo "✓ Global context remains $(docker context show)."

echo
echo "3. Verify runtime isolation"
echo "==========================="

colima_collision="$(
    docker \
        --context "${GLOBAL_CONTEXT}" \
        ps -a \
        --filter "name=^/${AUCTION_CONTAINER}$" \
        --format '{{.Names}}'
)"

if [[ -n "${colima_collision}" ]]; then
    fail "A conflicting ${AUCTION_CONTAINER} exists in Colima."
fi

docker \
    --context "${AUCTION_CONTEXT}" \
    inspect "${AUCTION_CONTAINER}" \
    >/dev/null 2>&1 ||
    fail \
        "The recovered container ${AUCTION_CONTAINER} is missing. Refusing to create a blank replacement."

mounted_volume="$(
    docker \
        --context "${AUCTION_CONTEXT}" \
        inspect "${AUCTION_CONTAINER}" \
        --format \
        '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}'
)"

if [[ "${mounted_volume}" != "${AUCTION_VOLUME}" ]]; then
    fail \
        "Unexpected database volume: ${mounted_volume:-none}; expected ${AUCTION_VOLUME}."
fi

published_port="$(
    docker \
        --context "${AUCTION_CONTEXT}" \
        port "${AUCTION_CONTAINER}" \
        5432/tcp \
        2>/dev/null |
        tail -1 |
        awk -F: '{print $NF}'
)"

if [[ "${published_port}" != "5444" ]]; then
    fail \
        "Unexpected PostgreSQL port: ${published_port:-none}; expected 5444."
fi

echo "✓ Container: ${AUCTION_CONTAINER}"
echo "✓ Volume   : ${mounted_volume}"
echo "✓ Port     : ${published_port}"
echo "✓ No matching Auction ETL container exists in Colima."

echo
echo "4. Start only the recovered Auction ETL container"
echo "================================================="

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

echo
echo "5. Wait for PostgreSQL and verify all recovered rows"
echo "===================================================="

database_ready=0

for attempt in $(seq 1 60); do
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
        tee -a "${LOG_PATH}" || true

    fail "PostgreSQL did not become ready on localhost:5444."
fi

verify_database ||
    fail "The database does not match the verified 775-row recovery."

echo "✓ Recovered database verified."

echo
echo "6. Write the private runtime configuration"
echo "=========================================="

cat > .auction-etl-runtime.env <<'ENV'
AUCTION_DOCKER_CONTEXT=desktop-linux
AUCTION_CONTAINER_NAME=auction-postgres-recovered
AUCTION_VOLUME_NAME=auction-etl_recovered_postgres_data
DATABASE_URL=postgresql://auction:auction@localhost:5444/auction_warehouse
ENV

chmod 600 .auction-etl-runtime.env

mkdir -p .git/info

grep -qxF '/.auction-etl-runtime.env' \
    .git/info/exclude \
    2>/dev/null ||
    echo '/.auction-etl-runtime.env' \
        >> .git/info/exclude

echo "✓ Runtime configuration remains private."

echo
echo "7. Create a verified pre-refresh backup"
echo "======================================="

run_logged \
    env \
    DOCKER_CONTEXT="${AUCTION_CONTEXT}" \
    DATABASE_URL="${DATABASE_URL}" \
    ./scripts/backup_auction_etl.sh ||
    fail "The pre-refresh backup failed."

restore_colima

echo
echo "8. Repair the Gripsweat configuration heredoc"
echo "=============================================="

[[ -f "${GRIPSWEAT_REFRESH}" ]] ||
    fail "Missing ${GRIPSWEAT_REFRESH}."

cp -p \
    "${GRIPSWEAT_REFRESH}" \
    "${PRIVATE_SCRIPT_BACKUP}/refresh_gripsweat_sources.sh"

python - <<'PY'
from __future__ import annotations

from pathlib import Path


path = Path("scripts/refresh_gripsweat_sources.sh")
source = path.read_text(encoding="utf-8")
lines = source.splitlines()

target_index: int | None = None

for index, line in enumerate(lines):
    if (
        'python - "${CONFIG_PATH}"' in line
        and "<<'PY'" in line
    ):
        target_index = index
        break

if target_index is None:
    raise SystemExit(
        "Could not locate the Gripsweat configuration heredoc."
    )

current = lines[target_index]

if '| tee -a "${RUN_LOG}"' not in current:
    indentation = current[
        : len(current) - len(current.lstrip())
    ]

    lines[target_index] = (
        indentation
        + 'python - "${CONFIG_PATH}" '
        + '2>&1 <<\'PY\' | tee -a "${RUN_LOG}"'
    )

    if target_index + 1 < len(lines):
        following = lines[target_index + 1].strip()

        if following in {
            'tee -a "${RUN_LOG}"',
            '| tee -a "${RUN_LOG}"',
            '2>&1 | tee -a "${RUN_LOG}"',
        }:
            del lines[target_index + 1]

updated = "\n".join(lines) + "\n"

required = (
    'python - "${CONFIG_PATH}" '
    '2>&1 <<\'PY\' | tee -a "${RUN_LOG}"'
)

if required not in updated:
    raise SystemExit(
        "The repaired heredoc could not be verified."
    )

path.write_text(
    updated,
    encoding="utf-8",
)

print("✓ Gripsweat configuration heredoc is valid.")
PY

patch_status=$?

if [[ "${patch_status}" -ne 0 ]]; then
    cp -p \
        "${PRIVATE_SCRIPT_BACKUP}/refresh_gripsweat_sources.sh" \
        "${GRIPSWEAT_REFRESH}"

    fail "The Gripsweat heredoc repair failed."
fi

chmod +x "${GRIPSWEAT_REFRESH}"

bash -n "${GRIPSWEAT_REFRESH}" ||
    fail "The Gripsweat refresh script has invalid shell syntax."

echo "✓ Gripsweat refresh script passed validation."

echo
echo "9. Compile all crawler and enrichment tools"
echo "==========================================="

required_python_scripts=(
    scripts/probe_gripsweat.py
    scripts/setup_gripsweat_schema.py
    scripts/import_gripsweat_probe.py
    scripts/audit_gripsweat_pagination.py
    scripts/import_gripsweat_pagination_audit.py
    scripts/enrich_gripsweat_details.py
    scripts/crawl_buyee_live_details.py
)

for script_path in "${required_python_scripts[@]}"; do
    [[ -f "${script_path}" ]] ||
        fail "Missing ${script_path}."

    chmod +x "${script_path}"
done

run_logged \
    python -m py_compile \
    "${required_python_scripts[@]}" ||
    fail "One or more crawler scripts failed compilation."

echo
echo "10. Refresh all configured Gripsweat sources"
echo "============================================"

run_logged \
    env \
    DOCKER_CONTEXT="${AUCTION_CONTEXT}" \
    DATABASE_URL="${DATABASE_URL}" \
    GRIPSWEAT_PAGES=10 \
    "${GRIPSWEAT_REFRESH}" ||
    fail "The configured Gripsweat refresh failed."

restore_colima

echo
echo "11. Test five Buyee pages without writes"
echo "========================================"

run_logged \
    env DATABASE_URL="${DATABASE_URL}" \
    python "${BUYEE_CRAWLER}" \
    --limit 5 \
    --refresh \
    --delay 2 \
    --timeout 45 \
    --log-dir \
    "logs/buyee/live-detail/${TIMESTAMP}/dry-run" ||
    fail "The five-page Buyee dry run failed."

echo
echo "12. Refresh all 77 known Buyee detail pages"
echo "==========================================="

run_logged \
    env DATABASE_URL="${DATABASE_URL}" \
    python "${BUYEE_CRAWLER}" \
    --apply \
    --refresh \
    --delay 2 \
    --timeout 45 \
    --log-dir \
    "logs/buyee/live-detail/${TIMESTAMP}/apply" ||
    fail "The Buyee detail refresh failed."

echo
echo "13. Rebuild collector classifications"
echo "====================================="

if [[ -f scripts/collector_features.py ]]; then
    run_logged \
        env DATABASE_URL="${DATABASE_URL}" \
        python scripts/collector_features.py ||
        fail "Collector feature rebuilding failed."
fi

if [[ -f scripts/reclassify_collector.py ]]; then
    run_logged \
        env DATABASE_URL="${DATABASE_URL}" \
        python scripts/reclassify_collector.py \
        --apply ||
        fail "Collector reclassification failed."
fi

echo
echo "14. Rebuild persistent USD values"
echo "================================"

if [[ -f scripts/update_auction_fx.py ]]; then
    run_logged \
        env DATABASE_URL="${DATABASE_URL}" \
        python scripts/update_auction_fx.py ||
        fail "USD conversion updating failed."
fi

echo
echo "15. Verify refreshed database coverage"
echo "======================================"

verify_database ||
    fail "The core recovered row state changed unexpectedly."

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
    COUNT(*) AS duplicate_groups
FROM (
    SELECT
        marketplace,
        listing_id
    FROM warehouse.auction
    GROUP BY
        marketplace,
        listing_id
    HAVING COUNT(*) > 1
) AS duplicates;

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
SQL

gripsweat_table="$(
    psql \
        "${DATABASE_URL}" \
        -At \
        -v ON_ERROR_STOP=1 \
        -c "
            SELECT COALESCE(
                to_regclass(
                    'warehouse.gripsweat_sale'
                )::text,
                ''
            );
        "
)"

[[ -n "${gripsweat_table}" ]] ||
    fail "warehouse.gripsweat_sale was not created."

psql \
    "${DATABASE_URL}" \
    -v ON_ERROR_STOP=1 <<'SQL' |
    tee -a "${LOG_PATH}"
SELECT
    configured_artist,
    COUNT(*) AS rows,
    COUNT(DISTINCT gripsweat_url)
        AS unique_urls,
    COUNT(sold_price) AS prices,
    COUNT(sold_at) AS sold_dates,
    COUNT(title) AS titles
FROM warehouse.gripsweat_sale
GROUP BY configured_artist
ORDER BY configured_artist;

SELECT
    COUNT(*) AS duplicate_url_groups
FROM (
    SELECT gripsweat_url
    FROM warehouse.gripsweat_sale
    GROUP BY gripsweat_url
    HAVING COUNT(*) > 1
) AS duplicates;
SQL

echo
echo "16. Run Auction ETL health checks"
echo "================================="

run_logged \
    env DATABASE_URL="${DATABASE_URL}" \
    python -m auction_etl.cli.main doctor run ||
    fail "Auction ETL doctor failed."

echo
echo "17. Create the verified post-refresh backup"
echo "==========================================="

run_logged \
    env \
    DOCKER_CONTEXT="${AUCTION_CONTEXT}" \
    DATABASE_URL="${DATABASE_URL}" \
    ./scripts/backup_auction_etl.sh ||
    fail "The post-refresh backup failed."

restore_colima

echo
echo "18. Restart Auction Collector Review"
echo "===================================="

run_logged \
    env \
    DOCKER_CONTEXT="${AUCTION_CONTEXT}" \
    DATABASE_URL="${DATABASE_URL}" \
    ./scripts/start_auction_etl.sh ||
    fail "Auction ETL startup failed."

restore_colima

ui_ready=0

for attempt in $(seq 1 45); do
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

if [[ "${ui_ready}" -ne 1 ]]; then
    tail -100 \
        logs/collector-ui/collector-review.log \
        2>/dev/null |
        tee -a "${LOG_PATH}" || true

    fail "Collector Review is not responding."
fi

echo "✓ Collector Review: http://127.0.0.1:8501"

echo
echo "19. Commit only the permanent successful workflow"
echo "================================================="

commit_paths=(
    scripts/finish_auction_source_refresh.sh
    scripts/refresh_gripsweat_sources.sh
    scripts/probe_gripsweat.py
    scripts/setup_gripsweat_schema.py
    scripts/import_gripsweat_probe.py
    scripts/audit_gripsweat_pagination.py
    scripts/import_gripsweat_pagination_audit.py
    scripts/enrich_gripsweat_details.py
    scripts/crawl_buyee_live_details.py
)

existing_commit_paths=()

for path in "${commit_paths[@]}"; do
    if [[ -f "${path}" ]]; then
        existing_commit_paths+=("${path}")
    fi
done

if [[ -f config/gripsweat_sources.json ]]; then
    existing_commit_paths+=(
        config/gripsweat_sources.json
    )
fi

git add -- "${existing_commit_paths[@]}"

git diff \
    --cached \
    --check ||
    fail "The staged source changes failed Git validation."

if git diff \
    --cached \
    --quiet
then
    echo "No permanent changes require a new commit."
else
    git commit \
        -m "fix: isolate and refresh auction sources" \
        -m "Keep Auction ETL on Docker Desktop while preserving Colima for Record Platform, repair the Gripsweat source refresh, and retain repeatable Gripsweat and Buyee detail crawls." ||
        fail "The source-refresh commit failed."
fi

restore_colima

echo
echo "SOURCE REFRESH COMPLETED"
echo "========================"
echo "✓ Auction ETL remains in Docker Desktop."
echo "✓ Colima remains the global Record Platform context."
echo "✓ The recovered 775 auction rows remain verified."
echo "✓ Gripsweat sources were refreshed."
echo "✓ All 77 known Buyee details were refreshed."
echo "✓ Collector classifications and USD values were rebuilt."
echo "✓ Pre-refresh and post-refresh backups were verified."
echo "✓ Collector Review is responding."
echo
echo "Global context: $(docker context show)"
echo "UI            : http://127.0.0.1:8501"
echo "Log           : ${LOG_PATH}"
echo
echo "Future command:"
echo
echo "    ./scripts/finish_auction_source_refresh.sh"
