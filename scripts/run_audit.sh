#!/usr/bin/env bash

PROJECT_DIR="${HOME}/auction-etl"

cd "${PROJECT_DIR}" || {
    echo "Could not open ${PROJECT_DIR}"
    return 1 2>/dev/null || true
}

source .venv/bin/activate || {
    echo "Could not activate .venv"
    return 1 2>/dev/null || true
}

mkdir -p logs

echo
echo "============================================================"
echo "Auction audit started: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "Python: $(which python)"
echo "============================================================"

set +e

python scripts/audit_collector_db.py "$@"
audit_status=$?

echo
echo "Audit exit status: ${audit_status}"

if [[ "${audit_status}" -eq 0 ]]; then
    echo "Audit completed successfully."
else
    echo "Audit failed, but this terminal remains open."
fi

echo "============================================================"

set -e 2>/dev/null || true

return 0 2>/dev/null || true
