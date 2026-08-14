#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(
    cd "$(dirname "${BASH_SOURCE[0]}")" &&
        pwd
)"

PROJECT_ROOT="$(
    cd "${SCRIPT_DIR}/.." &&
        pwd
)"

cd "${PROJECT_ROOT}"

PROFILE="auction-etl"
PROJECT_NAME="auction-etl"

COMPOSE_FILE="${PROJECT_ROOT}/compose.auction-etl.yml"
ENV_FILE="${PROJECT_ROOT}/.env.auction-etl.private"

PROFILE_SOCKET="${HOME}/.colima/${PROFILE}/docker.sock"
STACK_DOCKER_HOST="unix://${PROFILE_SOCKET}"

BACKUP_DIR="${PROJECT_ROOT}/backups/private/postgres"

ORIGINAL_CONTEXT="$(
    env \
        -u DOCKER_HOST \
        -u DOCKER_CONTEXT \
        docker context show \
        2>/dev/null ||
        true
)"

restore_original_context() {
    if [[ -n "${ORIGINAL_CONTEXT}" ]]; then
        env \
            -u DOCKER_HOST \
            -u DOCKER_CONTEXT \
            docker context use \
            "${ORIGINAL_CONTEXT}" \
            >/dev/null 2>&1 ||
            true
    fi
}

trap restore_original_context EXIT

fail() {
    echo
    echo "ERROR: $1"
    echo
    echo "No Record Platform container, volume, or database was targeted."

    exit 1
}

require_file() {
    local path="$1"

    [[ -f "${path}" ]] ||
        fail "Required file is missing: ${path}"
}

require_command() {
    local command_name="$1"

    command -v "${command_name}" >/dev/null 2>&1 ||
        fail "Required command is unavailable: ${command_name}"
}

load_environment() {
    require_file "${ENV_FILE}"

    set -a

    # shellcheck disable=SC1090
    source "${ENV_FILE}"

    set +a

    : "${POSTGRES_DB:?POSTGRES_DB is required}"
    : "${POSTGRES_USER:?POSTGRES_USER is required}"
    : "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
    : "${AUCTION_DB_PORT:?AUCTION_DB_PORT is required}"
    : "${AUCTION_UI_PORT:?AUCTION_UI_PORT is required}"
}

stack_docker() {
    env \
        -u DOCKER_CONTEXT \
        DOCKER_HOST="${STACK_DOCKER_HOST}" \
        docker "$@"
}

compose() {
    env \
        -u DOCKER_CONTEXT \
        DOCKER_HOST="${STACK_DOCKER_HOST}" \
        docker compose \
        --env-file "${ENV_FILE}" \
        --project-name "${PROJECT_NAME}" \
        --file "${COMPOSE_FILE}" \
        "$@"
}

profile_is_running() {
    colima status \
        --profile "${PROFILE}" \
        >/dev/null 2>&1
}

ensure_profile() {
    if ! profile_is_running; then
        echo
        echo "Starting isolated Auction ETL Colima profile"
        echo "============================================"

        colima start \
            --profile "${PROFILE}" \
            --runtime docker \
            --kubernetes=false \
            --cpu "${COLIMA_CPUS:-4}" \
            --memory "${COLIMA_MEMORY:-4}" \
            --disk "${COLIMA_DISK:-80}"
    fi

    restore_original_context

    for attempt in $(seq 1 60); do
        if [[ -S "${PROFILE_SOCKET}" ]] \
            && stack_docker info >/dev/null 2>&1
        then
            echo "✓ Auction ETL Docker daemon is ready."
            echo "✓ Socket: ${PROFILE_SOCKET}"
            return 0
        fi

        sleep 1
    done

    fail "The Auction ETL Colima Docker socket did not become ready."
}

service_is_running() {
    local service="$1"
    local container_id
    local running

    container_id="$(
        compose ps \
            --quiet \
            "${service}" \
            2>/dev/null ||
            true
    )"

    [[ -n "${container_id}" ]] || return 1

    running="$(
        stack_docker inspect \
            --format '{{.State.Running}}' \
            "${container_id}" \
            2>/dev/null ||
            true
    )"

    [[ "${running}" == "true" ]]
}

verify_available_port() {
    local port="$1"
    local service="$2"
    local label="$3"

    if ! lsof \
        -nP \
        -iTCP:"${port}" \
        -sTCP:LISTEN \
        >/dev/null 2>&1
    then
        return 0
    fi

    if service_is_running "${service}"; then
        return 0
    fi

    echo
    echo "${label} port ${port} is occupied:"
    lsof \
        -nP \
        -iTCP:"${port}" \
        -sTCP:LISTEN \
        2>/dev/null ||
        true

    fail "${label} port ${port} is occupied by another process."
}

wait_for_database() {
    local ready=0

    for attempt in $(seq 1 90); do
        if compose exec \
            --no-TTY \
            db \
            pg_isready \
            --username="${POSTGRES_USER}" \
            --dbname="${POSTGRES_DB}" \
            >/dev/null 2>&1
        then
            ready=1
            break
        fi

        sleep 2
    done

    if [[ "${ready}" -ne 1 ]]; then
        compose logs \
            --tail 150 \
            db \
            2>/dev/null ||
            true

        fail "PostgreSQL did not become ready."
    fi

    echo "✓ PostgreSQL is accepting connections."
}

latest_verified_backup() {
    find \
        "${BACKUP_DIR}" \
        -maxdepth 1 \
        -type f \
        -name 'auction_warehouse-*.dump' \
        -size +0c \
        -print \
        2>/dev/null |
        sort |
        tail -1
}

verify_backup_file() {
    local backup_path="$1"
    local checksum_path="${backup_path}.sha256"
    local expected_hash
    local actual_hash
    local temporary_manifest

    [[ -s "${backup_path}" ]] ||
        fail "Backup is empty: ${backup_path}"

    [[ -s "${checksum_path}" ]] ||
        fail "Backup checksum is missing: ${checksum_path}"

    expected_hash="$(
        awk 'NR == 1 {print $1}' \
            "${checksum_path}"
    )"

    actual_hash="$(
        shasum \
            -a 256 \
            "${backup_path}" |
            awk '{print $1}'
    )"

    if [[ -z "${expected_hash}" ]] \
        || [[ "${expected_hash}" != "${actual_hash}" ]]
    then
        fail "Backup checksum verification failed: ${backup_path}"
    fi

    temporary_manifest="$(mktemp)"

    if ! stack_docker run \
        --rm \
        --interactive \
        postgres:16-alpine \
        pg_restore \
        --list \
        < "${backup_path}" \
        > "${temporary_manifest}"
    then
        rm -f "${temporary_manifest}"

        fail "pg_restore could not read: ${backup_path}"
    fi

    if [[ ! -s "${temporary_manifest}" ]]; then
        rm -f "${temporary_manifest}"

        fail "Backup catalog is empty: ${backup_path}"
    fi

    rm -f "${temporary_manifest}"

    echo "✓ Verified restore archive: ${backup_path}"
}

database_table_exists() {
    local result

    result="$(
        compose exec \
            --no-TTY \
            db \
            psql \
            --username="${POSTGRES_USER}" \
            --dbname="${POSTGRES_DB}" \
            --tuples-only \
            --no-align \
            --command="
                SELECT to_regclass(
                    'warehouse.auction'
                );
            " \
            2>/dev/null |
            tr -d '[:space:]'
    )"

    [[ "${result}" == "warehouse.auction" ]]
}

database_core_state() {
    compose exec \
        --no-TTY \
        db \
        psql \
        --username="${POSTGRES_USER}" \
        --dbname="${POSTGRES_DB}" \
        --tuples-only \
        --no-align \
        --command="
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
        " |
        tr -d '[:space:]'
}

database_marketplace_state() {
    compose exec \
        --no-TTY \
        db \
        psql \
        --username="${POSTGRES_USER}" \
        --dbname="${POSTGRES_DB}" \
        --tuples-only \
        --no-align \
        --command="
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
        " |
        tr -d '[:space:]'
}

verify_recovered_database() {
    local identity
    local core_state
    local marketplace_state

    identity="$(
        compose exec \
            --no-TTY \
            db \
            psql \
            --username="${POSTGRES_USER}" \
            --dbname="${POSTGRES_DB}" \
            --tuples-only \
            --no-align \
            --command="
                SELECT
                    current_database()
                    || '|'
                    || current_user;
            " |
            tr -d '[:space:]'
    )"

    core_state="$(database_core_state)"
    marketplace_state="$(database_marketplace_state)"

    echo "Database identity : ${identity}"
    echo "Core state        : ${core_state}"
    echo "Marketplace state : ${marketplace_state}"

    [[ "${identity}" == "auction_warehouse|auction" ]] \
        || fail "Unexpected database identity: ${identity}"

    [[ "${core_state}" == "775|775" ]] \
        || fail "Unexpected recovered core state: ${core_state}"

    [[ "${marketplace_state}" == "buyee:77|ebay:698" ]] \
        || fail "Unexpected marketplace state: ${marketplace_state}"

    echo "✓ All 775 recovered auction keys are present."
}

restore_if_required() {
    local backup_path
    local database_container

    if database_table_exists; then
        echo "Existing Auction ETL database detected."

        verify_recovered_database

        return 0
    fi

    echo
    echo "Restoring the latest verified Auction ETL backup"
    echo "================================================"

    backup_path="$(latest_verified_backup)"

    [[ -n "${backup_path}" ]] ||
        fail "No verified private Auction ETL dump was found."

    verify_backup_file "${backup_path}"

    database_container="$(
        compose ps \
            --quiet \
            db
    )"

    [[ -n "${database_container}" ]] ||
        fail "The PostgreSQL container could not be located."

    compose exec \
        --no-TTY \
        db \
        psql \
        --username="${POSTGRES_USER}" \
        --dbname=postgres \
        --set=ON_ERROR_STOP=1 \
        --command="
            DROP DATABASE IF EXISTS
                \"${POSTGRES_DB}\"
            WITH (FORCE);
        "

    compose exec \
        --no-TTY \
        db \
        psql \
        --username="${POSTGRES_USER}" \
        --dbname=postgres \
        --set=ON_ERROR_STOP=1 \
        --command="
            CREATE DATABASE
                \"${POSTGRES_DB}\"
            OWNER
                \"${POSTGRES_USER}\";
        "

    stack_docker cp \
        "${backup_path}" \
        "${database_container}:/tmp/auction-restore.dump"

    compose exec \
        --no-TTY \
        db \
        pg_restore \
        --username="${POSTGRES_USER}" \
        --dbname="${POSTGRES_DB}" \
        --no-owner \
        --no-privileges \
        --exit-on-error \
        /tmp/auction-restore.dump

    compose exec \
        --no-TTY \
        db \
        rm -f \
        /tmp/auction-restore.dump

    verify_recovered_database

    echo "✓ Verified recovery dump restored into the isolated profile."
}

create_backup() {
    local project_root
    local backup_dir
    local database_user
    local database_name
    local timestamp
    local partial_backup
    local final_backup
    local partial_manifest
    local final_manifest
    local checksum_file
    local expected_hash
    local actual_hash

    project_root="${PROJECT_ROOT:-$(pwd)}"
    backup_dir="${BACKUP_DIR:-${project_root}/backups/private/postgres}"

    database_user="${POSTGRES_USER:-auction}"
    database_name="${POSTGRES_DB:-auction_warehouse}"

    timestamp="$(date +%Y%m%d-%H%M%S)"

    partial_backup="${backup_dir}/auction_warehouse-${timestamp}.dump.partial"
    final_backup="${backup_dir}/auction_warehouse-${timestamp}.dump"

    partial_manifest="${final_backup}.contents.txt.partial"
    final_manifest="${final_backup}.contents.txt"
    checksum_file="${final_backup}.sha256"

    mkdir -p "${backup_dir}"

    chmod 700 \
        "${project_root}/backups/private" \
        "${backup_dir}" \
        2>/dev/null || true

    rm -f \
        "${partial_backup}" \
        "${partial_manifest}"

    echo
    echo "Creating atomic PostgreSQL backup"
    echo "================================="

    if ! compose exec \
        -T \
        db \
        pg_dump \
        --username="${database_user}" \
        --dbname="${database_name}" \
        --format=custom \
        > "${partial_backup}"
    then
        rm -f \
            "${partial_backup}" \
            "${partial_manifest}"

        fail "pg_dump failed. No named backup was created."
    fi

    if [[ ! -s "${partial_backup}" ]]; then
        rm -f \
            "${partial_backup}" \
            "${partial_manifest}"

        fail "pg_dump produced an empty backup."
    fi

    if ! compose exec \
        -T \
        db \
        pg_restore \
        --list \
        < "${partial_backup}" \
        > "${partial_manifest}"
    then
        rm -f \
            "${partial_backup}" \
            "${partial_manifest}"

        fail "pg_restore could not verify the backup archive."
    fi

    if [[ ! -s "${partial_manifest}" ]]; then
        rm -f \
            "${partial_backup}" \
            "${partial_manifest}"

        fail "The backup catalog is empty."
    fi

    mv \
        "${partial_backup}" \
        "${final_backup}"

    mv \
        "${partial_manifest}" \
        "${final_manifest}"

    expected_hash="$(
        shasum -a 256 "${final_backup}" |
            awk '{print $1}'
    )"

    if [[ -z "${expected_hash}" ]]; then
        rm -f \
            "${final_backup}" \
            "${final_manifest}"

        fail "Could not calculate the backup checksum."
    fi

    printf '%s  %s\n' \
        "${expected_hash}" \
        "$(basename "${final_backup}")" \
        > "${checksum_file}"

    actual_hash="$(
        shasum -a 256 "${final_backup}" |
            awk '{print $1}'
    )"

    if [[ "${expected_hash}" != "${actual_hash}" ]]; then
        rm -f \
            "${final_backup}" \
            "${final_manifest}" \
            "${checksum_file}"

        fail "Backup checksum verification failed."
    fi

    chmod 600 \
        "${final_backup}" \
        "${final_manifest}" \
        "${checksum_file}"

    echo "✓ Verified backup: ${final_backup}"
    echo "✓ Manifest       : ${final_manifest}"
    echo "✓ SHA-256        : ${actual_hash}"
}

wait_for_ui() {
    local ready=0

    for attempt in $(seq 1 90); do
        if curl \
            --silent \
            --fail \
            "http://127.0.0.1:${AUCTION_UI_PORT}/_stcore/health" \
            >/dev/null 2>&1
        then
            ready=1
            break
        fi

        sleep 2
    done

    if [[ "${ready}" -ne 1 ]]; then
        compose logs \
            --tail 200 \
            collector \
            2>/dev/null ||
            true

        fail "Auction Collector Review did not become ready."
    fi

    echo "✓ Auction Collector Review is responding."
}

stop_old_host_ui() {
    pkill \
        -f 'streamlit run app/collector_review.py' \
        2>/dev/null ||
        true

    pkill \
        -f 'python.*app/collector_review.py' \
        2>/dev/null ||
        true

    sleep 1
}

command_up() {
    require_command colima
    require_command docker
    require_command curl
    require_command lsof
    require_command shasum

    require_file "${COMPOSE_FILE}"

    load_environment
    ensure_profile

    mkdir -p \
        exports \
        logs \
        profiles \
        reports \
        review \
        backups/private/postgres

    stop_old_host_ui

    verify_available_port \
        "${AUCTION_DB_PORT}" \
        db \
        "PostgreSQL"

    verify_available_port \
        "${AUCTION_UI_PORT}" \
        collector \
        "Collector Review"

    echo
    echo "Starting isolated PostgreSQL"
    echo "============================"

    compose up \
        --detach \
        db

    wait_for_database
    restore_if_required

    echo
    echo "Creating pre-UI verified backup"
    echo "==============================="

    create_backup

    echo
    echo "Building and starting Collector Review"
    echo "======================================"

    compose up \
        --detach \
        --build \
        collector

    wait_for_ui

    echo
    echo "Auction ETL is ready"
    echo "===================="
    echo "Database : postgresql://auction:***@127.0.0.1:${AUCTION_DB_PORT}/${POSTGRES_DB}"
    echo "UI       : http://127.0.0.1:${AUCTION_UI_PORT}"
    echo "Profile  : ${PROFILE}"
    echo "Volume   : auction-etl_postgres_data"
    echo
    echo "Global Docker context restored to:"
    echo "${ORIGINAL_CONTEXT:-unknown}"
    echo
    echo "Docker Desktop was not used."
    echo "Record Platform was not targeted."
}

command_down() {
    load_environment

    if ! profile_is_running; then
        echo "Auction ETL Colima profile is already stopped."
        return 0
    fi

    echo
    echo "Stopping Auction ETL containers"
    echo "==============================="

    compose stop \
        collector \
        db

    echo
    echo "Stopping only the Auction ETL Colima profile"
    echo "============================================"

    colima stop \
        --profile "${PROFILE}"

    restore_original_context

    echo
    echo "✓ Auction ETL is stopped."
    echo "✓ PostgreSQL volume was retained."
    echo "✓ Record Platform was not changed."
}

command_backup() {
    load_environment
    ensure_profile

    compose up \
        --detach \
        db

    wait_for_database
    verify_recovered_database
    create_backup
}

command_status() {
    load_environment

    echo
    echo "Auction ETL isolated stack status"
    echo "================================="
    echo "Profile        : ${PROFILE}"
    echo "Profile socket : ${PROFILE_SOCKET}"
    echo "Global context : ${ORIGINAL_CONTEXT:-unknown}"

    if ! profile_is_running; then
        echo "Status         : stopped"
        return 0
    fi

    echo "Status         : running"
    echo

    compose ps

    if service_is_running db; then
        echo
        verify_recovered_database
    fi
}

command_logs() {
    load_environment
    ensure_profile

    compose logs \
        --follow \
        --tail 200 \
        "${@:2}"
}

command_shell() {
    command_up

    compose exec \
        collector \
        bash
}

command_run() {
    if [[ "$#" -lt 2 ]]; then
        fail "Usage: $0 run <command> [arguments...]"
    fi

    load_environment
    ensure_profile

    compose up \
        --detach \
        db

    wait_for_database
    restore_if_required

    shift

    compose run \
        --rm \
        collector \
        "$@"
}

usage() {
    cat <<'USAGE'
Usage:
  ./scripts/auction_stack.sh up
  ./scripts/auction_stack.sh down
  ./scripts/auction_stack.sh backup
  ./scripts/auction_stack.sh status
  ./scripts/auction_stack.sh logs [db|collector]
  ./scripts/auction_stack.sh shell
  ./scripts/auction_stack.sh run <command> [arguments...]

Examples:
  ./scripts/auction_stack.sh up

  ./scripts/auction_stack.sh run \
      python -m auction_etl.cli.main doctor run

  ./scripts/auction_stack.sh run \
      python scripts/crawl_buyee_live_details.py \
      --limit 5 \
      --refresh \
      --delay 2 \
      --timeout 45 \
      --log-dir logs/buyee/container-test
USAGE
}

case "${1:-}" in
    up)
        command_up
        ;;
    down)
        command_down
        ;;
    backup)
        command_backup
        ;;
    status)
        command_status
        ;;
    logs)
        command_logs "$@"
        ;;
    shell)
        command_shell
        ;;
    run)
        command_run "$@"
        ;;
    *)
        usage
        exit 2
        ;;
esac
