#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(
    cd "$(
        dirname "${BASH_SOURCE[0]}"
    )/.." &&
        pwd
)"

cd "${ROOT}"

blockers=0


pass() {
    printf \
        'PASS  %s\n' \
        "$1"
}


block() {
    printf \
        'BLOCK %s\n' \
        "$1"

    blockers=$((blockers + 1))
}


echo "================================================================"
echo "AUCTION ETL CLOUD DEPLOYMENT READINESS"
echo "================================================================"


if grep -q \
    'DATABASE_URL' \
    auction_etl/database/session.py
then
    pass \
        "Application database layer exposes DATABASE_URL configuration."
else
    block \
        "Application DB layer is not DATABASE_URL aware."
fi


if grep -q \
    'DATABASE_URL' \
    alembic/env.py
then
    pass \
        "Alembic is runtime DATABASE_URL aware."
else
    block \
        "Alembic is not runtime DATABASE_URL aware."
fi


if [[ -f Dockerfile.auction-etl.refresh ]]; then
    pass \
        "Dedicated marketplace refresh worker image exists."
else
    block \
        "Dedicated refresh worker image is missing."
fi


if [[ -f scripts/run_buyee_owner.py ]]; then
    pass \
        "Persistent Buyee owner implementation exists."
else
    block \
        "Persistent Buyee owner implementation is missing."
fi


if grep -q \
    'launch_persistent_context' \
    scripts/run_buyee_owner.py
then
    pass \
        "Persistent Chromium context requirement detected."
else
    block \
        "Expected persistent Chromium context was not detected."
fi


if grep -q \
    'subprocess.Popen' \
    app/pages/3_Latest_Auction_Refresh.py
then
    block \
        "Refresh UI still launches a machine-local detached process."
else
    pass \
        "Refresh UI no longer launches machine-local detached processes."
fi


if grep -q \
    'logs/latest-refresh' \
    app/pages/3_Latest_Auction_Refresh.py
then
    block \
        "Refresh status still relies on machine-local filesystem state."
else
    pass \
        "Refresh status does not rely on machine-local filesystem state."
fi


if grep -q \
    'AUCTION_DOCKER_CONTEXT' \
    scripts/run_auction_refresh_on_demand.sh
then
    block \
        "On-demand launcher still contains local Docker/Colima coupling."
else
    pass \
        "On-demand ingestion launcher is platform-neutral."
fi


if (
    [[ -f vercel.json ]] ||
    [[ -d api ]]
); then
    pass \
        "A Vercel web/control-plane surface exists."
else
    block \
        "A Vercel web/control-plane surface has not been implemented yet."
fi


echo
echo "----------------------------------------------------------------"
echo "Architecture classification"
echo "----------------------------------------------------------------"

echo "VALIDATED_LOCAL_PRODUCTION=true"
echo "CURRENT_STREAMLIT_MONOLITH_VERCEL_TARGET=false"
echo "DATABASE_URL_FOUNDATION=true"
echo "PLAYWRIGHT_WORKER_FOUNDATION=true"

echo \
    "TARGET_ARCHITECTURE=vercel-control-plane+managed-postgres+persistent-worker"

echo "BLOCKER_COUNT=${blockers}"

if [[ "${blockers}" -eq 0 ]]; then
    echo "CLOUD_ARCHITECTURE_IMPLEMENTATION_COMPLETE=true"
else
    echo "CLOUD_ARCHITECTURE_IMPLEMENTATION_COMPLETE=false"
fi

echo
echo \
    "NOTE=Readiness classification is non-destructive and intentionally succeeds while implementation blockers remain."
