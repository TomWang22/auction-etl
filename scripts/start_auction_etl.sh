#!/usr/bin/env bash

set +e
set +u
set +o pipefail 2>/dev/null || true

cd "$HOME/auction-etl" || exit 1
source .venv/bin/activate 2>/dev/null || true

export DATABASE_URL="${DATABASE_URL:-postgresql://auction:auction@localhost:5444/auction_warehouse}"

echo
echo "Auction ETL startup"
echo "==================="

echo
echo "1. Ensure the isolated recovery database is ready"
echo "================================================="

./scripts/ensure_auction_postgres.sh

if [[ "$?" -ne 0 ]]; then
    echo
    echo "ERROR: Isolated Auction ETL PostgreSQL could not be verified."
    echo "No Record Platform resource was changed."
    exit 1
fi

echo
echo "2. Create an atomic verified database backup"
echo "============================================"

./scripts/backup_auction_etl.sh

if [[ "$?" -ne 0 ]]; then
    echo
    echo "ERROR: Startup stopped because the safety backup failed."
    exit 1
fi

echo
echo "3. Start Auction Collector Review"
echo "================================="

./scripts/start_collector_ui.sh

if [[ "$?" -ne 0 ]]; then
    echo
    echo "ERROR: Auction Collector Review failed to start."
    exit 1
fi

echo
echo "Auction ETL is ready"
echo "===================="
echo "Database: auction_warehouse"
echo "URL     : http://127.0.0.1:8501"
echo
echo "No Record Platform resource was changed."
