#!/usr/bin/env bash

set +e
set +u
set +o pipefail 2>/dev/null || true

DATABASE_URL="${DATABASE_URL:-postgresql://auction:auction@localhost:5444/auction_warehouse}"
CONTAINER_NAME="${AUCTION_POSTGRES_CONTAINER:-auction-postgres-recovered}"
VOLUME_NAME="${AUCTION_POSTGRES_VOLUME:-auction-etl_recovered_postgres_data}"
POSTGRES_IMAGE="${AUCTION_POSTGRES_IMAGE:-postgres:16-alpine}"

docker_context_usable() {
    local context_name="$1"

    docker \
        --context "${context_name}" \
        info \
        >/dev/null 2>&1
}

context_has_container() {
    local context_name="$1"

    docker_context_usable \
        "${context_name}" &&
    docker \
        --context "${context_name}" \
        inspect "${CONTAINER_NAME}" \
        >/dev/null 2>&1
}

context_has_volume() {
    local context_name="$1"

    docker_context_usable \
        "${context_name}" &&
    docker \
        --context "${context_name}" \
        volume inspect "${VOLUME_NAME}" \
        >/dev/null 2>&1
}

resolve_docker_context() {
    local requested_context
    local current_context
    local candidate_context

    requested_context="${AUCTION_DOCKER_CONTEXT:-}"

    if [[ -n "${requested_context}" ]]; then
        if context_has_container "${requested_context}" \
            || context_has_volume "${requested_context}"
        then
            printf '%s\n' "${requested_context}"
            return 0
        fi

        echo \
            "ERROR: Requested Docker context does not contain the isolated Auction ETL resource: ${requested_context}" \
            >&2
        return 1
    fi

    current_context="$(
        docker context show 2>/dev/null
    )"

    if [[ -n "${current_context}" ]]; then
        if context_has_container "${current_context}" \
            || context_has_volume "${current_context}"
        then
            printf '%s\n' "${current_context}"
            return 0
        fi
    fi

    while IFS= read -r candidate_context; do
        [[ -z "${candidate_context}" ]] && continue
        [[ "${candidate_context}" == "${current_context}" ]] && continue

        if context_has_container "${candidate_context}"; then
            printf '%s\n' "${candidate_context}"
            return 0
        fi
    done < <(
        docker context ls \
            --format '{{.Name}}' \
            2>/dev/null
    )

    while IFS= read -r candidate_context; do
        [[ -z "${candidate_context}" ]] && continue
        [[ "${candidate_context}" == "${current_context}" ]] && continue

        if context_has_volume "${candidate_context}"; then
            printf '%s\n' "${candidate_context}"
            return 0
        fi
    done < <(
        docker context ls \
            --format '{{.Name}}' \
            2>/dev/null
    )

    echo \
        "ERROR: No running Docker context contains ${CONTAINER_NAME} or ${VOLUME_NAME}." \
        >&2
    echo \
        "No Docker runtime was started automatically." \
        >&2
    return 1
}

verify_database() {
    local identity
    local row_verification
    local marketplace_verification

    identity="$(
        psql \
            "${DATABASE_URL}" \
            -At \
            -F '|' \
            -v ON_ERROR_STOP=1 \
            -c "
                SELECT
                    current_database(),
                    current_user;
            " \
            2>/dev/null
    )"

    if [[ "${identity}" != "auction_warehouse|auction" ]]; then
        echo "ERROR: Unexpected PostgreSQL identity:"
        echo "${identity:-unavailable}"
        return 1
    fi

    row_verification="$(
        psql \
            "${DATABASE_URL}" \
            -At \
            -F '|' \
            -v ON_ERROR_STOP=1 \
            -c "
                SELECT
                    COUNT(*),
                    COUNT(
                        DISTINCT (
                            marketplace,
                            listing_id
                        )
                    )
                FROM warehouse.auction;
            " \
            2>/dev/null
    )"

    if [[ "${row_verification}" != "775|775" ]]; then
        echo "ERROR: Recovered row verification failed:"
        echo "${row_verification:-unavailable}"
        return 1
    fi

    marketplace_verification="$(
        psql \
            "${DATABASE_URL}" \
            -At \
            -F '|' \
            -v ON_ERROR_STOP=1 \
            -c "
                SELECT
                    marketplace,
                    COUNT(*)
                FROM warehouse.auction
                GROUP BY marketplace
                ORDER BY marketplace;
            " \
            2>/dev/null
    )"

    if [[ "${marketplace_verification}" != $'buyee|77\nebay|698' ]]; then
        echo "ERROR: Marketplace row verification failed:"
        printf '%s\n' \
            "${marketplace_verification:-unavailable}"
        return 1
    fi

    echo "✓ Database identity: ${identity}"
    echo "✓ Core rows        : 775"
    echo "✓ Unique keys      : 775"
    echo "✓ Buyee rows       : 77"
    echo "✓ eBay rows        : 698"
}

if pg_isready \
    -h localhost \
    -p 5444 \
    -U auction \
    -d auction_warehouse \
    >/dev/null 2>&1
then
    echo "✓ Auction ETL PostgreSQL is already accepting connections."

    verify_database
    exit "$?"
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: Docker is unavailable."
    exit 1
fi

CONTEXT="$(
    resolve_docker_context
)"

if [[ "$?" -ne 0 ]] || [[ -z "${CONTEXT}" ]]; then
    exit 1
fi

echo "Docker context: ${CONTEXT}"

if docker \
    --context "${CONTEXT}" \
    inspect "${CONTAINER_NAME}" \
    >/dev/null 2>&1
then
    mounted_volume="$(
        docker \
            --context "${CONTEXT}" \
            inspect "${CONTAINER_NAME}" \
            --format \
            '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}' \
            2>/dev/null
    )"

    if [[ "${mounted_volume}" != "${VOLUME_NAME}" ]]; then
        echo "ERROR: ${CONTAINER_NAME} uses an unexpected database volume."
        echo "Expected: ${VOLUME_NAME}"
        echo "Found   : ${mounted_volume:-none}"
        exit 1
    fi

    postgres_database="$(
        docker \
            --context "${CONTEXT}" \
            inspect "${CONTAINER_NAME}" \
            --format '{{range .Config.Env}}{{println .}}{{end}}' \
            2>/dev/null |
        awk -F= '
            $1 == "POSTGRES_DB" {
                sub(
                    /^[^=]*=/,
                    ""
                )
                print
                exit
            }
        '
    )"

    postgres_user="$(
        docker \
            --context "${CONTEXT}" \
            inspect "${CONTAINER_NAME}" \
            --format '{{range .Config.Env}}{{println .}}{{end}}' \
            2>/dev/null |
        awk -F= '
            $1 == "POSTGRES_USER" {
                sub(
                    /^[^=]*=/,
                    ""
                )
                print
                exit
            }
        '
    )"

    if [[ "${postgres_database}" != "auction_warehouse" ]] \
        || [[ "${postgres_user}" != "auction" ]]
    then
        echo "ERROR: Isolated container environment is unexpected."
        echo "POSTGRES_DB  : ${postgres_database:-missing}"
        echo "POSTGRES_USER: ${postgres_user:-missing}"
        exit 1
    fi

    container_status="$(
        docker \
            --context "${CONTEXT}" \
            inspect "${CONTAINER_NAME}" \
            --format '{{.State.Status}}' \
            2>/dev/null
    )"

    case "${container_status}" in
        running)
            echo "Container is running; waiting for PostgreSQL."
            ;;
        created|exited|stopped)
            echo "Starting only ${CONTAINER_NAME}..."

            docker \
                --context "${CONTEXT}" \
                start "${CONTAINER_NAME}"

            if [[ "$?" -ne 0 ]]; then
                echo "ERROR: Could not start ${CONTAINER_NAME}."
                exit 1
            fi
            ;;
        *)
            echo "ERROR: Unexpected isolated container state:"
            echo "${container_status:-unknown}"
            exit 1
            ;;
    esac
else
    if ! docker \
        --context "${CONTEXT}" \
        volume inspect "${VOLUME_NAME}" \
        >/dev/null 2>&1
    then
        echo "ERROR: Recovered PostgreSQL volume is missing:"
        echo "${VOLUME_NAME}"
        echo "No empty replacement volume was created."
        exit 1
    fi

    echo "Recreating only the isolated Auction ETL container."
    echo "The existing recovered volume will be reused."

    docker \
        --context "${CONTEXT}" \
        run \
        --detach \
        --name "${CONTAINER_NAME}" \
        --restart unless-stopped \
        --env POSTGRES_DB=auction_warehouse \
        --env POSTGRES_USER=auction \
        --env POSTGRES_PASSWORD=auction \
        --publish 5444:5432 \
        --volume \
        "${VOLUME_NAME}:/var/lib/postgresql/data" \
        "${POSTGRES_IMAGE}"

    if [[ "$?" -ne 0 ]]; then
        echo "ERROR: Could not recreate ${CONTAINER_NAME}."
        exit 1
    fi
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
    echo
    echo "ERROR: Isolated Auction ETL PostgreSQL did not become ready."
    echo
    echo "Recent isolated-container log:"

    docker \
        --context "${CONTEXT}" \
        logs \
        --tail 120 \
        "${CONTAINER_NAME}" \
        2>&1

    exit 1
fi

verify_database
