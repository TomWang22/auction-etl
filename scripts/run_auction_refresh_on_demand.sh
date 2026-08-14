#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(
    cd "$(
        dirname "${BASH_SOURCE[0]}"
    )/.." &&
        pwd
)"

cd "${ROOT}"

DOCKER_CONTEXT_NAME="${AUCTION_DOCKER_CONTEXT:-colima}"
DATABASE_CONTAINER="${AUCTION_DB_CONTAINER:-auction-etl-db-1}"
DATABASE_HOST="${AUCTION_DATABASE_HOST:-127.0.0.1}"
DATABASE_PORT="${AUCTION_DATABASE_PORT:-5544}"
DATABASE_NAME="${AUCTION_DATABASE_NAME:-auction_warehouse}"
DATABASE_USER="${AUCTION_DATABASE_USER:-auction}"

DATABASE_URL="${DATABASE_URL:-postgresql://auction:auction@127.0.0.1:5544/auction_warehouse}"

PARENT="${ROOT}/scripts/run_multisource_ingestion_round.py"

PYTHON_CMD='python3'

if [[ -x "${ROOT}/.venv/bin/python3" ]]; then
    PYTHON_CMD="${ROOT}/.venv/bin/python3"
elif [[ -x "${ROOT}/.venv/bin/python" ]]; then
    PYTHON_CMD="${ROOT}/.venv/bin/python"
fi

fail() {
    printf '\nERROR: %s\n' "$1" >&2
    exit 1
}

for command_name in \
    docker \
    "${PYTHON_CMD}"
do
    command -v "${command_name}" >/dev/null 2>&1 ||
        fail "Missing command: ${command_name}"
done

[[ -f "${PARENT}" ]] ||
    fail "Missing canonical multisource ingestion runner: ${PARENT}"

active_context="$(
    docker context show
)"

[[ "${active_context}" == "${DOCKER_CONTEXT_NAME}" ]] ||
    fail \
        "Auction ingestion requires Docker context ${DOCKER_CONTEXT_NAME}; current context is ${active_context}."

container_state="$(
    docker \
        --context "${DOCKER_CONTEXT_NAME}" \
        inspect \
        --format \
        '{{.State.Running}}|{{.State.Health.Status}}' \
        "${DATABASE_CONTAINER}" \
        2>/dev/null
)" ||
    fail \
        "Auction ETL PostgreSQL container is unavailable: ${DATABASE_CONTAINER}"

[[ "${container_state}" == "true|healthy" ]] ||
    fail \
        "Auction ETL PostgreSQL is not healthy: ${container_state}"

published_binding="$(
    docker \
        --context "${DOCKER_CONTEXT_NAME}" \
        port \
        "${DATABASE_CONTAINER}" \
        5432/tcp \
        2>/dev/null |
        head -1
)"

[[ "${published_binding}" == "${DATABASE_HOST}:${DATABASE_PORT}" ]] ||
    fail \
        "Expected PostgreSQL at ${DATABASE_HOST}:${DATABASE_PORT}; found ${published_binding:-none}."

database_identity="$(
    docker \
        --context "${DOCKER_CONTEXT_NAME}" \
        exec \
        "${DATABASE_CONTAINER}" \
        sh \
        -lc '
            psql \
                -X \
                -v ON_ERROR_STOP=1 \
                -U "$POSTGRES_USER" \
                -d "$POSTGRES_DB" \
                -At \
                -c "
                    SELECT
                        current_database()
                        || '\''|'\'' ||
                        current_user;
                "
        '
)"

[[ "${database_identity}" == "${DATABASE_NAME}|${DATABASE_USER}" ]] ||
    fail \
        "Unexpected PostgreSQL identity: ${database_identity}"

export DATABASE_URL

echo
echo "Auction ETL on-demand marketplace ingestion"
echo "==========================================="
echo "Docker runtime : ${DOCKER_CONTEXT_NAME}"
echo "Database       : ${DATABASE_HOST}:${DATABASE_PORT}/${DATABASE_NAME}"
echo "Container      : ${DATABASE_CONTAINER}"
echo "Sources        : eBay, Buyee, Gripsweat"
echo
echo "Using the existing Colima Auction ETL PostgreSQL instance."
echo "No container recreation or database-runtime migration is performed."
echo

exec \
    "${PYTHON_CMD}" \
    "${PARENT}" \
    --database-url "${DATABASE_URL}" \
    --buyee-profile "${AUCTION_BUYEE_PROFILE:-anonymous}" \
    --execute
