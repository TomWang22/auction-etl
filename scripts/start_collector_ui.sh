#!/usr/bin/env bash

set +e
set +u
set +o pipefail 2>/dev/null || true

cd "$HOME/auction-etl" || exit 1
source .venv/bin/activate 2>/dev/null || true

export DATABASE_URL="${DATABASE_URL:-postgresql://auction:auction@localhost:5444/auction_warehouse}"

LOG_DIR="$HOME/auction-etl/logs/collector-ui"
PID_PATH="${LOG_DIR}/collector-review.pid"
LOG_PATH="${LOG_DIR}/collector-review.log"

mkdir -p \
    "${LOG_DIR}"

pkill -f \
    'streamlit run app/collector_review.py' \
    2>/dev/null || true

sleep 1

nohup \
    ./scripts/run_collector_ui.sh \
    > "${LOG_PATH}" \
    2>&1 &

process_id=$!

printf '%s\n' \
    "${process_id}" \
    > "${PID_PATH}"

ready=0

for attempt in $(seq 1 60); do
    if curl \
        --silent \
        --fail \
        http://127.0.0.1:8501 \
        >/dev/null 2>&1
    then
        ready=1
        break
    fi

    if ! kill -0 \
        "${process_id}" \
        2>/dev/null
    then
        break
    fi

    sleep 1
done

if [[ "${ready}" -ne 1 ]]; then
    echo "ERROR: Collector Review did not become ready."
    echo "Log: ${LOG_PATH}"
    tail -100 \
        "${LOG_PATH}" \
        2>/dev/null || true
    exit 1
fi

echo "✓ Auction Collector Review is responding."
echo "URL: http://127.0.0.1:8501"
echo "PID: ${process_id}"
echo "Log: ${LOG_PATH}"
