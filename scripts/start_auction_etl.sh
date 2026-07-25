#!/usr/bin/env bash

set +e
set +u
set +o pipefail 2>/dev/null || true

PROJECT_ROOT="${PROJECT_ROOT:-$HOME/auction-etl}"
DATABASE_URL="${DATABASE_URL:-postgresql://auction:auction@localhost:5444/auction_warehouse}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
UI_LOG="${PROJECT_ROOT}/logs/collector-ui/collector-ui-${TIMESTAMP}.log"

cd "${PROJECT_ROOT}" || {
    echo "ERROR: Cannot enter ${PROJECT_ROOT}"
    exit 1
}

source .venv/bin/activate 2>/dev/null || {
    echo "ERROR: Cannot activate .venv"
    exit 1
}

mkdir -p \
    logs/collector-ui \
    backups/private/postgres

echo
echo "Auction ETL startup"
echo "==================="
echo "Database: ${DATABASE_URL}"

pg_isready \
    -h localhost \
    -p 5444 \
    -U auction \
    -d auction_warehouse

if [[ "$?" -ne 0 ]]; then
    echo
    echo "ERROR: PostgreSQL is not ready on localhost:5444."
    echo "This command will not create or modify Docker containers."
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
    echo "ERROR: Unexpected PostgreSQL identity:"
    echo "${identity:-unavailable}"
    exit 1
fi

echo "✓ ${identity}"

echo
echo "Applying additive schema checks..."

DATABASE_URL="${DATABASE_URL}" \
    python scripts/upgrade_collector_review_schema.py

if [[ "$?" -ne 0 ]]; then
    echo "ERROR: Schema verification failed."
    exit 1
fi

echo
echo "Compiling application files..."

python -m py_compile \
    app/collector_review.py \
    scripts/upgrade_collector_review_schema.py \
    scripts/update_auction_fx.py \
    scripts/crawl_buyee_live_details.py

if [[ "$?" -ne 0 ]]; then
    echo "ERROR: Python compilation failed."
    exit 1
fi

echo
echo "Running Auction ETL health checks..."

python -m auction_etl.cli.main doctor run

if [[ "$?" -ne 0 ]]; then
    echo "ERROR: Auction ETL doctor failed."
    exit 1
fi

if [[ "${SKIP_BACKUP:-0}" != "1" ]]; then
    echo
    echo "Creating verified private startup backup..."

    DATABASE_URL="${DATABASE_URL}" \
        ./scripts/backup_auction_etl.sh

    if [[ "$?" -ne 0 ]]; then
        echo "ERROR: Startup backup failed."
        exit 1
    fi
else
    echo
    echo "Startup backup skipped because SKIP_BACKUP=1."
fi

echo
echo "Restarting only Auction Collector Review..."

pkill -f \
    'streamlit run app/collector_review.py' \
    2>/dev/null || true

pkill -f \
    'scripts/run_collector_ui.sh' \
    2>/dev/null || true

nohup \
    env DATABASE_URL="${DATABASE_URL}" \
    ./scripts/run_collector_ui.sh \
    > "${UI_LOG}" \
    2>&1 &

UI_PID=$!

disown "${UI_PID}" \
    2>/dev/null || true

ui_ready=0

for attempt in $(seq 1 45); do
    curl \
        --fail \
        --silent \
        http://127.0.0.1:8501 \
        >/dev/null 2>&1

    if [[ "$?" -eq 0 ]]; then
        ui_ready=1
        break
    fi

    sleep 1
done

echo

if [[ "${ui_ready}" -eq 1 ]]; then
    echo "Auction ETL is ready"
    echo "===================="
    echo "URL: http://127.0.0.1:8501"
    echo "PID: ${UI_PID}"
    echo "Log: ${UI_LOG}"
    echo
    echo "✓ Database identity verified."
    echo "✓ Schema checked."
    echo "✓ Python compiled."
    echo "✓ Health check passed."
    echo "✓ Private database backup verified."
    echo "✓ Collector UI is responding."
    exit 0
fi

echo "ERROR: Collector UI did not become ready."
echo "Log: ${UI_LOG}"
tail -100 "${UI_LOG}" 2>/dev/null || true
exit 1
