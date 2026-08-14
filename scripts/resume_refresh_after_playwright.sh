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

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
LOG_DIR="logs/source-refresh/${TIMESTAMP}"
LOG_PATH="${LOG_DIR}/docker-desktop-resume.log"

mkdir -p "${LOG_DIR}"
touch "${LOG_PATH}"

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
    echo "No Record Platform container or volume was targeted."

    restore_colima

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

verify_playwright() {
    python - <<'PY'
from pathlib import Path

from playwright.sync_api import sync_playwright


with sync_playwright() as playwright:
    executable = Path(playwright.chromium.executable_path)

    print(f"Chromium executable: {executable}")

    if not executable.is_file():
        raise SystemExit(
            f"Playwright Chromium is missing: {executable}"
        )
PY
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
                ) AS marketplace_counts;
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
echo "Auction ETL Docker Desktop recovery and refresh resume"
echo "======================================================"
echo "Database        : ${DATABASE_URL}"
echo "Auction context : ${AUCTION_CONTEXT}"
echo "Global context  : ${GLOBAL_CONTEXT}"
echo "Log             : ${LOG_PATH}"

echo
echo "1. Verify Playwright Chromium"
echo "============================="

verify_playwright ||
    fail "Playwright Chromium verification failed."

echo "✓ Playwright Chromium remains installed."

echo
echo "2. Verify Docker contexts"
echo "========================="

docker context inspect \
    "${AUCTION_CONTEXT}" \
    >/dev/null 2>&1 ||
    fail "Docker context ${AUCTION_CONTEXT} is missing."

docker context inspect \
    "${GLOBAL_CONTEXT}" \
    >/dev/null 2>&1 ||
    fail "Docker context ${GLOBAL_CONTEXT} is missing."

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

echo "Docker Desktop endpoint: ${desktop_endpoint}"
echo "Colima endpoint        : ${colima_endpoint}"

if [[ -z "${desktop_endpoint}" ]] \
    || [[ -z "${colima_endpoint}" ]] \
    || [[ "${desktop_endpoint}" == "${colima_endpoint}" ]]
then
    fail "Docker Desktop and Colima are not isolated."
fi

restore_colima

echo "✓ Global Docker context: $(docker context show)"

echo
echo "3. Start and wait for Docker Desktop"
echo "===================================="

if ! docker \
    --context "${AUCTION_CONTEXT}" \
    info \
    >/dev/null 2>&1
then
    echo "Docker Desktop is not ready."
    echo "Starting Docker Desktop..."

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
            elapsed_seconds=$((attempt * 2))

            echo \
                "Waiting for Docker Desktop: ${elapsed_seconds}s"
        fi

        sleep 2
    done

    if [[ "${desktop_ready}" -ne 1 ]]; then
        echo
        echo "Docker Desktop diagnostics"
        echo "--------------------------"

        echo
        echo "Processes:"
        ps aux |
            grep -Ei \
                'Docker|com\.docker|vpnkit' |
            grep -v grep |
            tee -a "${LOG_PATH}" ||
            true

        echo
        echo "Socket:"
        ls -la \
            "$HOME/.docker/run/docker.sock" \
            2>&1 |
            tee -a "${LOG_PATH}" ||
            true

        echo
        echo "Docker Desktop application:"
        osascript \
            -e 'application "Docker" is running' \
            2>&1 |
            tee -a "${LOG_PATH}" ||
            true

        fail "Docker Desktop did not become ready within five minutes."
    fi
fi

echo "✓ Docker Desktop daemon is available."

docker \
    --context "${GLOBAL_CONTEXT}" \
    info \
    >/dev/null 2>&1 ||
    fail "Colima became unavailable."

restore_colima

echo "✓ Colima remains available."
echo "✓ Global context remains $(docker context show)."

echo
echo "4. Verify the recovered Auction ETL container"
echo "============================================="

docker \
    --context "${AUCTION_CONTEXT}" \
    inspect "${AUCTION_CONTAINER}" \
    >/dev/null 2>&1 ||
    fail \
        "Recovered container ${AUCTION_CONTAINER} is missing."

mounted_volume="$(
    docker \
        --context "${AUCTION_CONTEXT}" \
        inspect "${AUCTION_CONTAINER}" \
        --format \
        '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}'
)"

if [[ "${mounted_volume}" != "${AUCTION_VOLUME}" ]]; then
    fail \
        "Unexpected database volume ${mounted_volume:-none}; expected ${AUCTION_VOLUME}."
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
        "Unexpected PostgreSQL port ${published_port:-none}; expected 5444."
fi

colima_collision="$(
    docker \
        --context "${GLOBAL_CONTEXT}" \
        ps -a \
        --filter "name=^/${AUCTION_CONTAINER}$" \
        --format '{{.Names}}'
)"

if [[ -n "${colima_collision}" ]]; then
    fail \
        "A conflicting ${AUCTION_CONTAINER} exists in Colima."
fi

echo "✓ Container: ${AUCTION_CONTAINER}"
echo "✓ Volume   : ${mounted_volume}"
echo "✓ Port     : ${published_port}"
echo "✓ No Auction ETL container exists in Colima."

echo
echo "5. Start only the recovered database container"
echo "=============================================="

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
echo "6. Wait for PostgreSQL"
echo "======================"

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
    echo
    echo "Recent Auction PostgreSQL logs:"
    echo "-------------------------------"

    docker \
        --context "${AUCTION_CONTEXT}" \
        logs \
        --tail 150 \
        "${AUCTION_CONTAINER}" \
        2>&1 |
        tee -a "${LOG_PATH}" ||
        true

    fail "PostgreSQL did not become ready on localhost:5444."
fi

echo "✓ PostgreSQL is accepting connections."

echo
echo "7. Verify all recovered database rows"
echo "====================================="

verify_database ||
    fail "The database does not match the verified 775-row state."

echo "✓ Recovered database verified."

echo
echo "8. Create another verified pre-refresh backup"
echo "============================================="

run_logged \
    env \
    DOCKER_CONTEXT="${AUCTION_CONTEXT}" \
    DATABASE_URL="${DATABASE_URL}" \
    ./scripts/backup_auction_etl.sh ||
    fail "The verified pre-refresh backup failed."

restore_colima

echo
echo "9. Resume the existing complete refresh workflow"
echo "================================================"

if [[ ! -x scripts/finish_auction_source_refresh.sh ]]; then
    fail \
        "scripts/finish_auction_source_refresh.sh is missing or not executable."
fi

bash -n scripts/finish_auction_source_refresh.sh ||
    fail "The existing refresh workflow has invalid shell syntax."

set +e

env \
    DATABASE_URL="${DATABASE_URL}" \
    ./scripts/finish_auction_source_refresh.sh \
    2>&1 |
    tee -a "${LOG_PATH}"

workflow_status="${PIPESTATUS[0]}"

set -e

restore_colima

echo
echo "Existing workflow status: ${workflow_status}"

if [[ "${workflow_status}" -ne 0 ]]; then
    fail \
        "The source refresh reached a later failure. Review the first ERROR above."
fi

echo
echo "10. Final runtime verification"
echo "=============================="

verify_database ||
    fail "Final database verification failed."

curl \
    --silent \
    --fail \
    http://127.0.0.1:8501 \
    >/dev/null 2>&1 ||
    fail "Collector Review is not responding."

restore_colima

echo
echo "REFRESH RESUME COMPLETED"
echo "========================"
echo "✓ Playwright Chromium remains installed."
echo "✓ Docker Desktop became available."
echo "✓ Colima remains the global context."
echo "✓ The recovered 775 auction rows remain verified."
echo "✓ Gripsweat and Buyee refresh processing completed."
echo "✓ Collector Review is responding."
echo
echo "UI : http://127.0.0.1:8501"
echo "Log: ${LOG_PATH}"
