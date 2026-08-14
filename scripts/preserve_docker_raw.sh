#!/usr/bin/env bash

set +e
set +u
set +o pipefail 2>/dev/null || true

SOURCE="$HOME/Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw"
RECOVERY_ROOT="${RECOVERY_ROOT:-}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

fail() {
    echo
    echo "ERROR: $1"
    echo "Nothing was modified."
    return 1
}

echo
echo "Auction ETL Docker.raw preservation"
echo "==================================="

if [[ ! -f "${SOURCE}" ]]; then
    fail "Docker.raw was not found at ${SOURCE}"
    exit_code=$?
    exit "${exit_code}"
fi

echo "Source: ${SOURCE}"
echo

echo "Mounted volumes"
echo "---------------"

find /Volumes \
    -mindepth 1 \
    -maxdepth 1 \
    -type d \
    -print \
    2>/dev/null

echo

if [[ -z "${RECOVERY_ROOT}" ]]; then
    echo "RECOVERY_ROOT is not set."
    echo
    echo "Choose an external mounted volume and run:"
    echo
    echo 'RECOVERY_ROOT="/Volumes/Your Drive Name" \'
    echo '    ./scripts/preserve_docker_raw.sh'
    echo
    echo "No copy was attempted."
    exit 2
fi

if [[ ! -d "${RECOVERY_ROOT}" ]]; then
    fail "Recovery destination is not mounted: ${RECOVERY_ROOT}"
    exit_code=$?
    exit "${exit_code}"
fi

destination_device="$(
    df -P "${RECOVERY_ROOT}" 2>/dev/null |
        awk 'NR == 2 {print $1}'
)"

source_device="$(
    df -P "${SOURCE}" 2>/dev/null |
        awk 'NR == 2 {print $1}'
)"

echo "Recovery root : ${RECOVERY_ROOT}"
echo "Source device : ${source_device:-unknown}"
echo "Target device : ${destination_device:-unknown}"
echo

if [[ -n "${source_device}" ]] \
    && [[ "${source_device}" == "${destination_device}" ]]
then
    fail "The recovery destination is on the same filesystem as Docker.raw."
    exit_code=$?
    exit "${exit_code}"
fi

echo "Checking whether Docker.raw is open..."
open_processes="$(lsof "${SOURCE}" 2>/dev/null)"

if [[ -n "${open_processes}" ]]; then
    echo
    echo "Docker.raw is still open:"
    printf '%s\n' "${open_processes}"
    echo
    echo "Fully quit Docker Desktop, wait 30 seconds, and rerun."
    exit 3
fi

echo "✓ Docker.raw is not open."

source_logical_bytes="$(stat -f '%z' "${SOURCE}")"
source_allocated_kb="$(
    du -k "${SOURCE}" 2>/dev/null |
        awk '{print $1}'
)"
destination_free_kb="$(
    df -Pk "${RECOVERY_ROOT}" 2>/dev/null |
        awk 'NR == 2 {print $4}'
)"
required_kb="$(
    awk \
        -v allocated="${source_allocated_kb:-0}" \
        'BEGIN {
            printf "%.0f", allocated * 1.20
        }'
)"

echo
echo "Capacity verification"
echo "---------------------"
echo "Logical source bytes : ${source_logical_bytes}"
echo "Allocated source KB  : ${source_allocated_kb:-unknown}"
echo "Required free KB     : ${required_kb}"
echo "Available target KB  : ${destination_free_kb:-unknown}"

if [[ -z "${destination_free_kb}" ]] \
    || [[ "${destination_free_kb}" -lt "${required_kb}" ]]
then
    fail "The destination does not have enough available space."
    exit_code=$?
    exit "${exit_code}"
fi

DESTINATION_DIR="${RECOVERY_ROOT}/auction-etl-forensics-${TIMESTAMP}"
DESTINATION="${DESTINATION_DIR}/Docker.raw"
MANIFEST="${DESTINATION_DIR}/manifest.txt"

mkdir -p "${DESTINATION_DIR}"

if [[ "$?" -ne 0 ]]; then
    fail "Could not create ${DESTINATION_DIR}"
    exit_code=$?
    exit "${exit_code}"
fi

{
    echo "Auction ETL Docker.raw forensic preservation"
    echo "Created: $(date)"
    echo
    echo "Source: ${SOURCE}"
    echo "Destination: ${DESTINATION}"
    echo
    echo "Source metadata"
    echo "---------------"
    stat -x "${SOURCE}"
    echo
    echo "Source logical size"
    echo "-------------------"
    ls -lh "${SOURCE}"
    echo
    echo "Source allocated size"
    echo "---------------------"
    du -h "${SOURCE}"
} > "${MANIFEST}"

echo
echo "Copying Docker.raw"
echo "------------------"
echo "Destination: ${DESTINATION}"
echo
echo "This may take a long time."

if command -v rsync >/dev/null 2>&1; then
    rsync \
        -aS \
        --info=progress2 \
        "${SOURCE}" \
        "${DESTINATION}"

    copy_status=$?
else
    echo "rsync is unavailable; using sparse cp."

    cp \
        -p \
        -c \
        "${SOURCE}" \
        "${DESTINATION}"

    copy_status=$?
fi

if [[ "${copy_status}" -ne 0 ]]; then
    echo
    echo "ERROR: Copy failed with status ${copy_status}."
    echo "Partial output was retained at:"
    echo "${DESTINATION}"
    exit "${copy_status}"
fi

destination_logical_bytes="$(
    stat -f '%z' "${DESTINATION}"
)"

if [[ "${destination_logical_bytes}" != "${source_logical_bytes}" ]]; then
    echo
    echo "ERROR: Logical file sizes differ."
    echo "Source      : ${source_logical_bytes}"
    echo "Destination : ${destination_logical_bytes}"
    exit 4
fi

{
    echo
    echo "Destination metadata"
    echo "--------------------"
    stat -x "${DESTINATION}"
    echo
    echo "Destination logical size"
    echo "------------------------"
    ls -lh "${DESTINATION}"
    echo
    echo "Destination allocated size"
    echo "--------------------------"
    du -h "${DESTINATION}"
} >> "${MANIFEST}"

echo
echo "Calculating SHA-256 hashes"
echo "--------------------------"
echo "This may take a long time."

source_hash="$(
    shasum -a 256 "${SOURCE}" |
        awk '{print $1}'
)"

destination_hash="$(
    shasum -a 256 "${DESTINATION}" |
        awk '{print $1}'
)"

{
    echo
    echo "SHA-256"
    echo "-------"
    echo "Source      : ${source_hash}"
    echo "Destination : ${destination_hash}"
} >> "${MANIFEST}"

if [[ -z "${source_hash}" ]] \
    || [[ "${source_hash}" != "${destination_hash}" ]]
then
    echo
    echo "ERROR: SHA-256 hashes do not match."
    echo "Manifest: ${MANIFEST}"
    exit 5
fi

chmod a-w "${DESTINATION}" 2>/dev/null || true

echo
echo "Preservation completed"
echo "======================"
echo "Copy     : ${DESTINATION}"
echo "Manifest : ${MANIFEST}"
echo "SHA-256  : ${destination_hash}"
echo
echo "✓ Source and destination hashes match."
echo "✓ The original Docker.raw was not modified."
