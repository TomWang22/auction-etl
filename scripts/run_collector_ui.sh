#!/usr/bin/env bash

set +e
set +u
set +o pipefail 2>/dev/null || true

cd "$HOME/auction-etl" || exit 1
source .venv/bin/activate 2>/dev/null || true

export DATABASE_URL="${DATABASE_URL:-postgresql://auction:auction@localhost:5444/auction_warehouse}"

exec streamlit run \
    app/collector_review.py \
    --server.address 127.0.0.1 \
    --server.port 8501 \
    --server.headless true
