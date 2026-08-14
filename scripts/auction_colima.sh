#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(git rev-parse --show-toplevel)"
source .venv/bin/activate

DOCKER_CONTEXT_NAME="${DOCKER_CONTEXT_NAME:-colima}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-auction-etl}"
DATABASE_SERVICE="${AUCTION_DATABASE_SERVICE:-db}"
PREFERRED_CONTAINER="${AUCTION_DB_CONTAINER:-auction-etl-db-1}"

DATABASE_HOST="${AUCTION_DATABASE_HOST:-127.0.0.1}"
DATABASE_PORT="${AUCTION_DATABASE_PORT:-5544}"
DATABASE_NAME="${AUCTION_DATABASE_NAME:-auction_warehouse}"
DATABASE_USER="${AUCTION_DATABASE_USER:-auction}"
DATABASE_PASSWORD="${AUCTION_DB_PASSWORD:-auction}"

EXPECTED_REVISION="${AUCTION_EXPECTED_REVISION:-c8b4d7e2a619}"
MINIMUM_AUCTION_ROWS="${AUCTION_MINIMUM_ROWS:-848}"
MINIMUM_ASSIGNMENTS="${AUCTION_MINIMUM_ASSIGNMENTS:-6}"

export DOCKER_CONTEXT="${DOCKER_CONTEXT_NAME}"
export COMPOSE_PROJECT_NAME
export DATABASE_URL="postgresql+psycopg://${DATABASE_USER}:${DATABASE_PASSWORD}@${DATABASE_HOST}:${DATABASE_PORT}/${DATABASE_NAME}"
export PSQL_URL="postgresql://${DATABASE_USER}:${DATABASE_PASSWORD}@${DATABASE_HOST}:${DATABASE_PORT}/${DATABASE_NAME}"
export PGPASSWORD="${DATABASE_PASSWORD}"
export PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-10}"

ACTION="${1:-start}"

if [[ $# -gt 0 ]]; then
    shift
fi

fail() {
    printf '\nERROR: %s\n' "$1" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage:
  scripts/auction_colima.sh status
  scripts/auction_colima.sh start
  scripts/auction_colima.sh run <command> [arguments...]

Examples:
  scripts/auction_colima.sh start

  scripts/auction_colima.sh run \
      python scripts/run_ingest_with_assignment_queue.py

  scripts/auction_colima.sh run \
      python scripts/run_ingest_with_assignment_queue.py --execute

Safety:
  - Uses Docker context "colima".
  - Never opens Docker Desktop.
  - Never creates a container, volume, or database.
  - Requires the existing auction-etl PostgreSQL volume.
  - Requires fixed host port 5544.
EOF
}

extract_revision() {
    awk '
        $1 ~ /^[0-9a-f]{12,40}$/ && !found {
            print $1
            found = 1
        }
    '
}

postgres_healthy() {
    pg_isready \
        -h "${DATABASE_HOST}" \
        -p "${DATABASE_PORT}" \
        -U "${DATABASE_USER}" \
        -d "${DATABASE_NAME}" \
        >/dev/null 2>&1
}

wait_for_postgres() {
    local attempt

    for attempt in $(seq 1 120); do
        if postgres_healthy; then
            return 0
        fi

        sleep 1
    done

    return 1
}

scalar() {
    psql \
        "${PSQL_URL}" \
        --no-password \
        -v ON_ERROR_STOP=1 \
        -Atc "$1"
}

streamlit_healthy() {
    curl \
        --fail \
        --silent \
        --show-error \
        --max-time 5 \
        http://127.0.0.1:8501/_stcore/health \
        >/dev/null 2>&1
}

find_exact_container() {
    local container_id
    local container_name

    for container_id in $(
        docker \
            --context "${DOCKER_CONTEXT_NAME}" \
            ps -aq
    ); do
        container_name="$(
            docker \
                --context "${DOCKER_CONTEXT_NAME}" \
                inspect \
                --format '{{.Name}}' \
                "${container_id}" |
            sed 's#^/##'
        )"

        if [[ "${container_name}" == "${PREFERRED_CONTAINER}" ]]; then
            printf '%s\n' "${container_id}"
            return 0
        fi
    done

    return 1
}

find_project_container() {
    docker \
        --context "${DOCKER_CONTEXT_NAME}" \
        ps -aq \
        --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" \
        --filter "label=com.docker.compose.service=${DATABASE_SERVICE}"
}

select_database_container() {
    local exact_container
    local candidates
    local candidate_count

    exact_container="$(
        find_exact_container ||
        true
    )"

    if [[ -n "${exact_container}" ]]; then
        printf '%s\n' "${exact_container}"
        return 0
    fi

    candidates="$(
        find_project_container
    )"

    candidate_count="$(
        printf '%s\n' "${candidates}" |
        awk 'NF {count += 1} END {print count + 0}'
    )"

    if [[ "${candidate_count}" -eq 1 ]]; then
        printf '%s\n' "${candidates}"
        return 0
    fi

    if [[ "${candidate_count}" -gt 1 ]]; then
        echo "Matching Colima containers:"
        printf '%s\n' "${candidates}"

        fail \
            "Multiple ${COMPOSE_PROJECT_NAME}/${DATABASE_SERVICE} containers exist."
    fi

    return 1
}

inspect_database_binding() {
    local container_id="$1"

    docker \
        --context "${DOCKER_CONTEXT_NAME}" \
        inspect \
        --format \
        '{{with index .NetworkSettings.Ports "5432/tcp"}}{{range .}}{{.HostIp}}|{{.HostPort}}{{println}}{{end}}{{end}}' \
        "${container_id}" |
    awk 'NF {print; exit}'
}

inspect_named_volumes() {
    local container_id="$1"

    docker \
        --context "${DOCKER_CONTEXT_NAME}" \
        inspect "${container_id}" |
    python -c '
from __future__ import annotations

import json
import sys


inspection = json.load(sys.stdin)[0]

for mount in inspection.get("Mounts", []):
    if mount.get("Type") != "volume":
        continue

    name = str(mount.get("Name") or "").strip()
    destination = str(
        mount.get("Destination")
        or ""
    ).strip()

    if name:
        print(f"{name}|{destination}")
'
}

ensure_colima() {
    command -v colima >/dev/null 2>&1 ||
        fail "Colima is not installed."

    command -v docker >/dev/null 2>&1 ||
        fail "Docker CLI is not installed."

    if ! colima status >/dev/null 2>&1; then
        echo "Starting the existing Colima VM..."

        colima start
    fi

    docker context inspect \
        "${DOCKER_CONTEXT_NAME}" \
        >/dev/null 2>&1 ||
        fail "Docker context ${DOCKER_CONTEXT_NAME} does not exist."

    docker context use \
        "${DOCKER_CONTEXT_NAME}" \
        >/dev/null

    export DOCKER_CONTEXT="${DOCKER_CONTEXT_NAME}"

    docker \
        --context "${DOCKER_CONTEXT_NAME}" \
        info \
        >/dev/null 2>&1 ||
        fail "The Colima Docker API is unavailable."

    echo "✓ Colima is running."
    echo "✓ Docker context: ${DOCKER_CONTEXT_NAME}"
    echo "✓ Docker Desktop is not required."
}

ensure_existing_database() {
    local container_id
    local container_name
    local binding
    local host_ip
    local host_port
    local named_volumes
    local running

    container_id="$(
        select_database_container ||
        true
    )"

    if [[ -z "${container_id}" ]]; then
        echo
        echo "Colima containers:"

        docker \
            --context "${DOCKER_CONTEXT_NAME}" \
            ps -a \
            --format \
            'table {{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Ports}}'

        echo
        echo "Colima volumes:"

        docker \
            --context "${DOCKER_CONTEXT_NAME}" \
            volume ls

        fail \
            "The existing ${COMPOSE_PROJECT_NAME} database container was not found. Nothing was created."
    fi

    container_name="$(
        docker \
            --context "${DOCKER_CONTEXT_NAME}" \
            inspect \
            --format '{{.Name}}' \
            "${container_id}" |
        sed 's#^/##'
    )"

    binding="$(
        inspect_database_binding \
            "${container_id}" ||
        true
    )"

    [[ -n "${binding}" ]] ||
        fail \
            "Container ${container_name} has no fixed PostgreSQL host-port binding."

    host_ip="${binding%%|*}"
    host_port="${binding#*|}"

    [[ "${host_port}" == "${DATABASE_PORT}" ]] ||
        fail \
            "Container ${container_name} publishes PostgreSQL on ${host_port}, not ${DATABASE_PORT}. It was not recreated."

    named_volumes="$(
        inspect_named_volumes \
            "${container_id}"
    )"

    [[ -n "${named_volumes}" ]] ||
        fail \
            "Container ${container_name} does not use an existing named volume."

    echo "Database container:"
    echo "  ${container_name}"
    echo
    echo "Port binding:"
    echo "  ${host_ip:-0.0.0.0}:${host_port} -> 5432"
    echo
    echo "Persistent volume mount(s):"
    printf '%s\n' "${named_volumes}" |
    sed 's/^/  /'

    docker \
        --context "${DOCKER_CONTEXT_NAME}" \
        update \
        --restart unless-stopped \
        "${container_id}" \
        >/dev/null

    running="$(
        docker \
            --context "${DOCKER_CONTEXT_NAME}" \
            inspect \
            --format '{{.State.Running}}' \
            "${container_id}"
    )"

    if [[ "${running}" != "true" ]]; then
        echo "Starting existing database container ${container_name}..."

        docker \
            --context "${DOCKER_CONTEXT_NAME}" \
            start \
            "${container_id}" \
            >/dev/null
    fi

    if ! wait_for_postgres; then
        docker \
            --context "${DOCKER_CONTEXT_NAME}" \
            logs \
            --tail 200 \
            "${container_id}" ||
        true

        fail \
            "The existing Colima PostgreSQL container did not become healthy."
    fi

    echo "✓ Existing persistent PostgreSQL is healthy on port ${DATABASE_PORT}."
}

verify_database() {
    local current_revision
    local head_revision
    local auction_rows
    local assignments
    local queue_rows
    local snapshots
    local timeline

    current_revision="$(
        uv run alembic current 2>&1 |
        extract_revision
    )"

    head_revision="$(
        uv run alembic heads 2>&1 |
        extract_revision
    )"

    auction_rows="$(
        scalar '
            SELECT COUNT(*)
            FROM warehouse.auction;
        '
    )"

    assignments="$(
        scalar '
            SELECT COUNT(*)
            FROM warehouse.auction_pressing_assignment;
        '
    )"

    snapshots="$(
        scalar '
            SELECT COUNT(*)
            FROM system.listing_completeness_snapshot;
        '
    )"

    timeline="$(
        scalar '
            SELECT COUNT(*)
            FROM system.listing_completeness_timeline;
        '
    )"

    queue_rows="$(
        scalar '
            SELECT COUNT(*)
            FROM system.new_auction_assignment_queue;
        '
    )"

    echo
    echo "Database verification:"
    echo "  Current revision:       ${current_revision}"
    echo "  Repository head:        ${head_revision}"
    echo "  Auction rows:           ${auction_rows}"
    echo "  Reviewed assignments:   ${assignments}"
    echo "  Completeness snapshots: ${snapshots}"
    echo "  Timeline events:        ${timeline}"
    echo "  Unassigned queue rows:  ${queue_rows}"

    [[ "${current_revision}" == "${EXPECTED_REVISION}" ]] ||
        fail \
            "Database revision ${current_revision:-EMPTY} does not match ${EXPECTED_REVISION}."

    [[ "${head_revision}" == "${EXPECTED_REVISION}" ]] ||
        fail \
            "Repository head ${head_revision:-EMPTY} does not match ${EXPECTED_REVISION}."

    [[ "${auction_rows}" -ge "${MINIMUM_AUCTION_ROWS}" ]] ||
        fail \
            "Expected at least ${MINIMUM_AUCTION_ROWS} auctions; found ${auction_rows}."

    [[ "${assignments}" -ge "${MINIMUM_ASSIGNMENTS}" ]] ||
        fail \
            "Expected at least ${MINIMUM_ASSIGNMENTS} reviewed assignments."

    [[ "$((auction_rows - assignments))" -eq "${queue_rows}" ]] ||
        fail \
            "The queue does not equal auction rows minus reviewed assignments."

    echo "✓ The correct auction-etl warehouse is connected."
}

ensure_collector_review() {
    local streamlit_log
    local streamlit_pid
    local attempt

    if streamlit_healthy; then
        echo "✓ Collector Review is already healthy on port 8501."
        return 0
    fi

    if lsof \
        -nP \
        -iTCP:8501 \
        -sTCP:LISTEN \
        >/dev/null 2>&1
    then
        fail \
            "Port 8501 is occupied by an unhealthy process. It was not terminated."
    fi

    mkdir -p logs/runtime

    streamlit_log="logs/runtime/collector-review-colima.log"

    nohup env \
        DOCKER_CONTEXT="${DOCKER_CONTEXT_NAME}" \
        DATABASE_URL="${DATABASE_URL}" \
        PYTHONUNBUFFERED=1 \
        python -m streamlit run \
            app/collector_review.py \
            --server.address 127.0.0.1 \
            --server.port 8501 \
            --server.headless true \
            --browser.gatherUsageStats false \
        >"${streamlit_log}" 2>&1 &

    streamlit_pid=$!

    for attempt in $(seq 1 90); do
        if streamlit_healthy; then
            echo "✓ Collector Review started."
            echo "  PID: ${streamlit_pid}"
            echo "  Log: ${streamlit_log}"
            return 0
        fi

        if ! kill -0 "${streamlit_pid}" 2>/dev/null; then
            break
        fi

        sleep 1
    done

    tail -n 200 "${streamlit_log}" ||
        true

    fail "Collector Review failed to start."
}

main() {
    case "${ACTION}" in
        -h|--help|help)
            usage
            return 0
            ;;
        status|start|run)
            ;;
        *)
            usage
            fail "Unsupported action: ${ACTION}"
            ;;
    esac

    echo "================ COLIMA AUCTION-ETL ================"

    ensure_colima
    ensure_existing_database
    verify_database

    case "${ACTION}" in
        status)
            ;;
        start)
            ensure_collector_review

            echo
            echo "Open:"
            echo "  http://127.0.0.1:8501"
            ;;
        run)
            [[ $# -gt 0 ]] ||
                fail "The run action requires a command."

            echo
            echo "================ RUN WITH COLIMA CONTEXT ================"
            echo "DOCKER_CONTEXT=${DOCKER_CONTEXT_NAME}"
            echo "DATABASE_URL=${DATABASE_URL}"
            echo "Command:"
            printf '  %q' "$@"
            printf '\n\n'

            exec "$@"
            ;;
    esac
}

main "$@"
