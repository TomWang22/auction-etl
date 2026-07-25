#!/usr/bin/env bash

set +e
set +u
set +o pipefail 2>/dev/null || true

cd "$HOME/auction-etl" || exit 1

DATABASE_URL="${DATABASE_URL:-postgresql://auction:auction@localhost:5444/auction_warehouse}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/auction-etl/backups/private/postgres}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

FINAL_PATH="${BACKUP_DIR}/auction_warehouse-${TIMESTAMP}.dump"
FINAL_CONTENTS="${FINAL_PATH}.contents.txt"

PARTIAL_PATH="${FINAL_PATH}.partial"
PARTIAL_CONTENTS="${FINAL_CONTENTS}.partial"

cleanup_partial_files() {
    rm -f \
        "${PARTIAL_PATH}" \
        "${PARTIAL_CONTENTS}" \
        2>/dev/null || true
}

trap cleanup_partial_files EXIT

mkdir -p \
    "${BACKUP_DIR}"

if ! pg_isready \
    -h localhost \
    -p 5444 \
    -U auction \
    -d auction_warehouse \
    >/dev/null 2>&1
then
    echo "ERROR: Auction ETL PostgreSQL is unavailable."
    exit 1
fi

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
    echo "ERROR: Unexpected database identity:"
    echo "${identity:-unavailable}"
    exit 1
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
    echo "ERROR: Refusing to back up an unverified recovery state:"
    echo "${row_verification:-unavailable}"
    exit 1
fi

pg_dump \
    "${DATABASE_URL}" \
    --format=custom \
    --no-owner \
    --no-acl \
    --file="${PARTIAL_PATH}"

if [[ "$?" -ne 0 ]] || [[ ! -s "${PARTIAL_PATH}" ]]; then
    echo "ERROR: pg_dump failed or produced an empty file."
    exit 1
fi

pg_restore \
    --list \
    "${PARTIAL_PATH}" \
    > "${PARTIAL_CONTENTS}"

if [[ "$?" -ne 0 ]] || [[ ! -s "${PARTIAL_CONTENTS}" ]]; then
    echo "ERROR: Backup verification failed."
    exit 1
fi

mv \
    "${PARTIAL_PATH}" \
    "${FINAL_PATH}"

if [[ "$?" -ne 0 ]]; then
    echo "ERROR: Could not finalize the database backup."
    exit 1
fi

mv \
    "${PARTIAL_CONTENTS}" \
    "${FINAL_CONTENTS}"

if [[ "$?" -ne 0 ]]; then
    echo "ERROR: Could not finalize the backup manifest."
    exit 1
fi

trap - EXIT

backup_hash="$(
    shasum \
        -a 256 \
        "${FINAL_PATH}" |
    awk '{print $1}'
)"

if [[ -z "${backup_hash}" ]]; then
    echo "ERROR: Could not calculate the backup hash."
    exit 1
fi

printf '%s  %s\n' \
    "${backup_hash}" \
    "$(basename "${FINAL_PATH}")" \
    > "${FINAL_PATH}.sha256"

echo "✓ Verified backup: ${FINAL_PATH}"
echo "✓ Manifest       : ${FINAL_CONTENTS}"
echo "✓ SHA-256        : ${backup_hash}"
