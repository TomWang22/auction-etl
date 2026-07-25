#!/usr/bin/env bash

set +e
set +u
set +o pipefail 2>/dev/null || true

cd "$HOME/auction-etl" || exit 1
source .venv/bin/activate 2>/dev/null || true

export DATABASE_URL="${DATABASE_URL:-postgresql://auction:auction@localhost:5444/auction_warehouse}"

pg_isready \
    -h localhost \
    -p 5444 \
    -U auction \
    -d auction_warehouse

if [[ "$?" -ne 0 ]]; then
    echo "ERROR: Auction ETL PostgreSQL is unavailable on port 5444."
    echo "No Record Platform service was touched."
    exit 1
fi

./scripts/backup_auction_etl.sh

if [[ "$?" -ne 0 ]]; then
    echo "ERROR: Startup stopped because the safety backup failed."
    exit 1
fi

./scripts/start_collector_ui.sh
