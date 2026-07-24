#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${HOME}/auction-etl"

cd "${PROJECT_DIR}"

if [[ ! -x ".venv/bin/python" ]]; then
    echo "Missing project virtual environment."
    echo "Run: uv sync"
    exit 1
fi

source .venv/bin/activate

exec python -m streamlit run \
    app/collector_review.py \
    --server.address 127.0.0.1 \
    --server.port 8501 \
    --browser.gatherUsageStats false
