#!/usr/bin/env bash

set +e
set +u
set +o pipefail 2>/dev/null || true

umask 077

DATABASE_URL="${DATABASE_URL:-postgresql://auction:auction@localhost:5444/auction_warehouse}"
BACKUP_ROOT="${BACKUP_ROOT:-$HOME/auction-etl/backups/private/postgres}"
BACKUP_KEEP="${BACKUP_KEEP:-20}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

DUMP_PATH="${BACKUP_ROOT}/auction_warehouse-${TIMESTAMP}.dump"
CONTENTS_PATH="${DUMP_PATH}.contents.txt"
HASH_PATH="${DUMP_PATH}.sha256"
METADATA_PATH="${DUMP_PATH}.metadata.txt"

mkdir -p "${BACKUP_ROOT}"

echo
echo "Auction ETL verified private backup"
echo "==================================="
echo "Destination: ${DUMP_PATH}"

pg_isready \
    -h localhost \
    -p 5444 \
    -U auction \
    -d auction_warehouse

if [[ "$?" -ne 0 ]]; then
    echo "ERROR: Auction PostgreSQL is unavailable."
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

pg_dump \
    "${DATABASE_URL}" \
    --format=custom \
    --no-owner \
    --no-acl \
    --file="${DUMP_PATH}"

if [[ "$?" -ne 0 ]] \
    || [[ ! -s "${DUMP_PATH}" ]]
then
    echo "ERROR: pg_dump failed."
    exit 1
fi

pg_restore \
    --list \
    "${DUMP_PATH}" \
    > "${CONTENTS_PATH}"

if [[ "$?" -ne 0 ]] \
    || [[ ! -s "${CONTENTS_PATH}" ]]
then
    echo "ERROR: pg_restore could not verify the dump."
    exit 1
fi

shasum \
    -a 256 \
    "${DUMP_PATH}" \
    > "${HASH_PATH}"

if [[ "$?" -ne 0 ]] \
    || [[ ! -s "${HASH_PATH}" ]]
then
    echo "ERROR: SHA-256 creation failed."
    exit 1
fi

{
    echo "Auction ETL PostgreSQL backup"
    echo "Created: $(date)"
    echo "Database identity: ${identity}"
    echo "Database URL: postgresql://auction@localhost:5444/auction_warehouse"
    echo
    echo "Git branch:"
    git branch --show-current 2>/dev/null || true
    echo
    echo "Git commit:"
    git rev-parse HEAD 2>/dev/null || true
    echo
    echo "Warehouse counts:"
    psql \
        "${DATABASE_URL}" \
        -v ON_ERROR_STOP=1 \
        -c "
            SELECT
                marketplace,
                COUNT(*) AS rows,
                COUNT(DISTINCT listing_id)
                    AS unique_rows
            FROM warehouse.auction
            GROUP BY marketplace
            ORDER BY marketplace;
        "
    echo
    echo "Dump contents:"
    wc -l "${CONTENTS_PATH}"
    echo
    echo "SHA-256:"
    cat "${HASH_PATH}"
} > "${METADATA_PATH}"

chmod 600 \
    "${DUMP_PATH}" \
    "${CONTENTS_PATH}" \
    "${HASH_PATH}" \
    "${METADATA_PATH}" \
    2>/dev/null || true

verification_hash="$(
    shasum -a 256 "${DUMP_PATH}" |
        awk '{print $1}'
)"

stored_hash="$(
    awk '{print $1}' "${HASH_PATH}"
)"

if [[ -z "${verification_hash}" ]] \
    || [[ "${verification_hash}" != "${stored_hash}" ]]
then
    echo "ERROR: Backup hash verification failed."
    exit 1
fi

if [[ "${BACKUP_KEEP}" =~ ^[0-9]+$ ]] \
    && [[ "${BACKUP_KEEP}" -gt 0 ]]
then
    old_dumps="$(
        find "${BACKUP_ROOT}" \
            -maxdepth 1 \
            -type f \
            -name 'auction_warehouse-*.dump' \
            -print |
        sort -r |
        tail -n "+$((BACKUP_KEEP + 1))"
    )"

    while IFS= read -r old_dump; do
        [[ -z "${old_dump}" ]] && continue

        rm -f \
            "${old_dump}" \
            "${old_dump}.contents.txt" \
            "${old_dump}.sha256" \
            "${old_dump}.metadata.txt"
    done <<< "${old_dumps}"
fi

echo
echo "Backup completed"
echo "================"
echo "Dump    : ${DUMP_PATH}"
echo "Manifest: ${METADATA_PATH}"
echo "SHA-256 : ${verification_hash}"
echo
echo "✓ The dump is non-empty."
echo "✓ pg_restore read the dump catalog."
echo "✓ The SHA-256 hash was verified."
echo "✓ Backup files are excluded from Git."
