#!/usr/bin/env bash

set +e
set +u
set +o pipefail 2>/dev/null || true

cd "$HOME/auction-etl" || exit 1

DATABASE_URL="${DATABASE_URL:-postgresql://auction:auction@localhost:5444/auction_warehouse}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/auction-etl/backups/private/postgres}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_PATH="${BACKUP_DIR}/auction_warehouse-${TIMESTAMP}.dump"
CONTENTS_PATH="${BACKUP_PATH}.contents.txt"

mkdir -p \
    "${BACKUP_DIR}"

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
    echo "ERROR: Unexpected database identity: ${identity:-unavailable}"
    exit 1
fi

pg_dump \
    "${DATABASE_URL}" \
    --format=custom \
    --no-owner \
    --no-acl \
    --file="${BACKUP_PATH}"

if [[ "$?" -ne 0 ]]; then
    echo "ERROR: pg_dump failed."
    exit 1
fi

pg_restore \
    --list \
    "${BACKUP_PATH}" \
    > "${CONTENTS_PATH}"

if [[ "$?" -ne 0 ]] \
    || [[ ! -s "${CONTENTS_PATH}" ]]
then
    echo "ERROR: Backup verification failed."
    exit 1
fi

find "${BACKUP_DIR}" \
    -type f \
    -name 'auction_warehouse-*.dump' \
    -mtime +30 \
    -delete \
    2>/dev/null || true

find "${BACKUP_DIR}" \
    -type f \
    -name 'auction_warehouse-*.dump.contents.txt' \
    -mtime +30 \
    -delete \
    2>/dev/null || true

echo "✓ Verified backup: ${BACKUP_PATH}"
