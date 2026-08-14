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

RUNTIME_ENV="${PROJECT_ROOT}/.auction-etl-runtime.env"

if [[ ! -f "${RUNTIME_ENV}" ]]; then
    echo "ERROR: Missing private runtime configuration:"
    echo "${RUNTIME_ENV}"
    exit 1
fi

# shellcheck disable=SC1090
source "${RUNTIME_ENV}"

AUCTION_DOCKER_CONTEXT="${AUCTION_DOCKER_CONTEXT:-desktop-linux}"
AUCTION_CONTAINER_NAME="${AUCTION_CONTAINER_NAME:-auction-postgres-recovered}"
AUCTION_VOLUME_NAME="${AUCTION_VOLUME_NAME:-auction-etl_recovered_postgres_data}"
DATABASE_URL="${DATABASE_URL:-postgresql://auction:auction@localhost:5444/auction_warehouse}"

BACKUP_DIR="${PROJECT_ROOT}/backups/private/postgres"

fail() {
    echo
    echo "ERROR: $1"
    echo "No Colima or Record Platform resource was changed."
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
            " \
            2>/dev/null
    )" || return 1

    if [[ "${identity}" != "auction_warehouse|auction" ]]; then
        echo "Unexpected database identity: ${identity:-unknown}"
        return 1
    fi

    core_state="$(
        psql \
            "${DATABASE_URL}" \
            -At \
            -v ON_ERROR_STOP=1 \
            -c "
                SELECT
                    CASE
                        WHEN to_regclass(
                            'warehouse.auction'
                        ) IS NULL
                        THEN 'missing'
                        ELSE (
                            SELECT
                                COUNT(*)
                                || '|'
                                || COUNT(
                                    DISTINCT (
                                        marketplace,
                                        listing_id
                                    )
                                )
                            FROM warehouse.auction
                        )
                    END;
            " \
            2>/dev/null
    )" || return 1

    if [[ "${core_state}" != "775|775" ]]; then
        echo "Unexpected core row state: ${core_state}"
        return 1
    fi

    marketplace_state="$(
        psql \
            "${DATABASE_URL}" \
            -At \
            -v ON_ERROR_STOP=1 \
            -c "
                SELECT string_agg(
                    marketplace || ':' || row_count,
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
            " \
            2>/dev/null
    )" || return 1

    if [[ "${marketplace_state}" != "buyee:77|ebay:698" ]]; then
        echo "Unexpected marketplace state: ${marketplace_state}"
        return 1
    fi

    echo "✓ Database identity: ${identity}"
    echo "✓ Core rows        : 775"
    echo "✓ Unique keys      : 775"
    echo "✓ Buyee rows       : 77"
    echo "✓ eBay rows        : 698"

    return 0
}

find_verified_backup() {
    local candidate
    local expected_hash
    local actual_hash

    while IFS= read -r candidate; do
        [[ -n "${candidate}" ]] || continue
        [[ -s "${candidate}" ]] || continue
        [[ -s "${candidate}.sha256" ]] || continue

        expected_hash="$(
            awk 'NR == 1 {print $1}' \
                "${candidate}.sha256"
        )"

        actual_hash="$(
            shasum -a 256 "${candidate}" |
                awk '{print $1}'
        )"

        [[ -n "${expected_hash}" ]] || continue
        [[ "${expected_hash}" == "${actual_hash}" ]] || continue

        if ! pg_restore \
            --list \
            "${candidate}" \
            >/dev/null 2>&1
        then
            continue
        fi

        printf '%s\n' "${candidate}"
        return 0
    done < <(
        find \
            "${BACKUP_DIR}" \
            -maxdepth 1 \
            -type f \
            -name 'auction_warehouse-*.dump' \
            -print \
            2>/dev/null |
        sort -r
    )

    return 1
}

echo
echo "Auction ETL PostgreSQL verification"
echo "==================================="
echo "Docker context: ${AUCTION_DOCKER_CONTEXT}"
echo "Container     : ${AUCTION_CONTAINER_NAME}"
echo "Volume        : ${AUCTION_VOLUME_NAME}"

if [[ "${AUCTION_DOCKER_CONTEXT}" == "colima" ]]; then
    fail "Auction ETL is forbidden from using the Colima context."
fi

if ! docker \
    context inspect "${AUCTION_DOCKER_CONTEXT}" \
    >/dev/null 2>&1
then
    fail "Docker context ${AUCTION_DOCKER_CONTEXT} does not exist."
fi

colima_endpoint="$(
    docker context inspect colima \
        --format '{{.Endpoints.docker.Host}}' \
        2>/dev/null ||
        true
)"

auction_endpoint="$(
    docker context inspect "${AUCTION_DOCKER_CONTEXT}" \
        --format '{{.Endpoints.docker.Host}}' \
        2>/dev/null ||
        true
)"

if [[ -n "${colima_endpoint}" ]] \
    && [[ "${auction_endpoint}" == "${colima_endpoint}" ]]
then
    fail "Auction ETL context resolves to the Colima Docker endpoint."
fi

if ! docker \
    --context "${AUCTION_DOCKER_CONTEXT}" \
    info \
    >/dev/null 2>&1
then
    if [[ "${AUCTION_DOCKER_CONTEXT}" != "desktop-linux" ]]; then
        fail "The pinned Auction ETL Docker daemon is unavailable."
    fi

    echo "Starting Docker Desktop..."

    open -a Docker

    desktop_ready=0

    for attempt in $(seq 1 90); do
        if docker \
            --context "${AUCTION_DOCKER_CONTEXT}" \
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

if pg_isready \
    -h localhost \
    -p 5444 \
    -U auction \
    -d auction_warehouse \
    >/dev/null 2>&1
then
    if verify_database; then
        echo "✓ Auction ETL PostgreSQL is already accepting connections."
        exit 0
    fi

    fail "Port 5444 serves an unexpected PostgreSQL database."
fi

port_owner="$(
    lsof \
        -nP \
        -iTCP:5444 \
        -sTCP:LISTEN \
        2>/dev/null ||
        true
)"

if [[ -n "${port_owner}" ]]; then
    printf '%s\n' "${port_owner}"
    fail "Port 5444 is occupied by another process."
fi

if ! docker \
    --context "${AUCTION_DOCKER_CONTEXT}" \
    volume inspect "${AUCTION_VOLUME_NAME}" \
    >/dev/null 2>&1
then
    docker \
        --context "${AUCTION_DOCKER_CONTEXT}" \
        volume create "${AUCTION_VOLUME_NAME}" \
        >/dev/null

    echo "✓ Created isolated Auction ETL volume."
else
    echo "✓ Found isolated Auction ETL volume."
fi

if docker \
    --context "${AUCTION_DOCKER_CONTEXT}" \
    inspect "${AUCTION_CONTAINER_NAME}" \
    >/dev/null 2>&1
then
    mounted_volume="$(
        docker \
            --context "${AUCTION_DOCKER_CONTEXT}" \
            inspect "${AUCTION_CONTAINER_NAME}" \
            --format \
            '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}'
    )"

    port_bindings="$(
        docker \
            --context "${AUCTION_DOCKER_CONTEXT}" \
            inspect "${AUCTION_CONTAINER_NAME}" \
            --format \
            '{{json (index .HostConfig.PortBindings "5432/tcp")}}'
    )"

    if [[ "${mounted_volume}" != "${AUCTION_VOLUME_NAME}" ]]; then
        fail "Existing Auction ETL container uses an unexpected volume."
    fi

    if ! printf '%s\n' "${port_bindings}" |
        grep -q '"HostPort":"5444"'
    then
        fail "Existing Auction ETL container is not mapped to port 5444."
    fi

    docker \
        --context "${AUCTION_DOCKER_CONTEXT}" \
        start "${AUCTION_CONTAINER_NAME}" \
        >/dev/null

    echo "✓ Started existing isolated Auction ETL container."
else
    docker \
        --context "${AUCTION_DOCKER_CONTEXT}" \
        run \
        --detach \
        --name "${AUCTION_CONTAINER_NAME}" \
        --restart unless-stopped \
        --env POSTGRES_DB=auction_warehouse \
        --env POSTGRES_USER=auction \
        --env POSTGRES_PASSWORD=auction \
        --publish 127.0.0.1:5444:5432 \
        --volume \
        "${AUCTION_VOLUME_NAME}:/var/lib/postgresql/data" \
        postgres:16-alpine \
        >/dev/null

    echo "✓ Created isolated Auction ETL container."
fi

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
        --context "${AUCTION_DOCKER_CONTEXT}" \
        logs \
        --tail 100 \
        "${AUCTION_CONTAINER_NAME}" \
        2>&1 ||
        true

    fail "Auction ETL PostgreSQL did not become ready."
fi

if verify_database; then
    echo "✓ Existing recovered Auction ETL database is healthy."
    exit 0
fi

auction_table="$(
    psql \
        "${DATABASE_URL}" \
        -At \
        -v ON_ERROR_STOP=1 \
        -c "
            SELECT to_regclass(
                'warehouse.auction'
            );
        " \
        2>/dev/null ||
        true
)"

user_table_count="$(
    psql \
        "${DATABASE_URL}" \
        -At \
        -v ON_ERROR_STOP=1 \
        -c "
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema NOT IN (
                'pg_catalog',
                'information_schema'
            );
        " \
        2>/dev/null ||
        printf 'unknown'
)"

if [[ -n "${auction_table}" ]]; then
    fail "Existing warehouse.auction data is not the expected 775-row state."
fi

if [[ "${user_table_count}" != "0" ]]; then
    fail "The recovery database is not empty; automatic restore was refused."
fi

latest_backup="$(
    find_verified_backup
)" || fail "No checksum-verified private backup was found."

echo
echo "Restoring verified backup"
echo "========================="
echo "${latest_backup}"

pg_restore \
    --exit-on-error \
    --no-owner \
    --no-privileges \
    --dbname="${DATABASE_URL}" \
    "${latest_backup}"

if ! verify_database; then
    fail "The restored database failed row validation."
fi

echo
echo "✓ Auction ETL database was restored successfully."
echo "✓ Docker context: ${AUCTION_DOCKER_CONTEXT}"
echo "✓ Colima was not used."
