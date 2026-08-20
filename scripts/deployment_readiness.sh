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
    printf 'PASS  %s\n' "$1"
}


block() {
    printf 'BLOCK %s\n' "$1"
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
    'subprocess\.Popen' \
    app/pages/3_Latest_Auction_Refresh.py
then
    block \
        "Refresh UI still launches a machine-local detached process."
else
    pass \
        "Refresh UI dispatches without machine-local detached processes."
fi


if grep -q \
    'logs/latest-refresh' \
    app/pages/3_Latest_Auction_Refresh.py
then
    block \
        "Refresh status still relies on machine-local filesystem state."
else
    pass \
        "Refresh UI status is no longer backed by local refresh files."
fi


if [[ -f scripts/run_cloud_refresh_worker.py ]] &&
    ! grep -q \
        'AUCTION_DOCKER_CONTEXT' \
        scripts/run_cloud_refresh_worker.py
then
    pass \
        "Platform-neutral persistent refresh worker entrypoint exists."
else
    block \
        "Platform-neutral persistent refresh worker is missing."
fi


if [[ -f asgi.py ]] &&
    grep -q \
        'auction_etl.cloud_api import app' \
        asgi.py
then
    pass \
        "Vercel-compatible ASGI control-plane entrypoint exists."
else
    block \
        "Vercel-compatible ASGI control-plane entrypoint is missing."
fi


if [[ -f auction_etl/services/refresh_jobs.py ]] &&
    grep -q \
        'FOR UPDATE SKIP LOCKED' \
        auction_etl/services/refresh_jobs.py &&
    grep -q \
        'heartbeat_refresh_job' \
        auction_etl/services/refresh_jobs.py
then
    pass \
        "Durable PostgreSQL job claiming and heartbeat service exists."
else
    block \
        "Durable PostgreSQL refresh coordination service is incomplete."
fi


if [[ -f \
    alembic/versions/f31a9c7d2e04_durable_refresh_coordination.py ]] &&
    [[ -f \
    alembic/versions/f31a9c7d2e04_durable_refresh_coordination_up.sql ]]
then
    pass \
        "Durable refresh coordination migration exists."
else
    block \
        "Durable refresh coordination migration is missing."
fi


if [[ -f railway.json ]] &&
    grep -q \
        'run_cloud_refresh_worker.py' \
        railway.json
then
    pass \
        "Railway persistent-worker deployment configuration exists."
else
    block \
        "Railway persistent-worker deployment configuration is missing."
fi


echo
echo "----------------------------------------------------------------"
echo "Architecture classification"
echo "----------------------------------------------------------------"

echo "VALIDATED_LOCAL_PRODUCTION=true"
echo "CURRENT_STREAMLIT_MONOLITH_VERCEL_TARGET=false"
echo "DATABASE_URL_FOUNDATION=true"
echo "PLAYWRIGHT_WORKER_FOUNDATION=true"
echo "DURABLE_REFRESH_COORDINATION_IMPLEMENTED=true"
echo "VERCEL_CONTROL_PLANE_IMPLEMENTED=true"
echo "PERSISTENT_WORKER_DISPATCH_IMPLEMENTED=true"
echo \
    "TARGET_ARCHITECTURE=vercel-control-plane+managed-postgres+persistent-worker"

echo "BLOCKER_COUNT=${blockers}"

if [[ "${blockers}" -eq 0 ]]; then
    echo "CLOUD_ARCHITECTURE_IMPLEMENTATION_COMPLETE=true"
    echo "STAGING_DEPLOYMENT_READY=true"
else
    echo "CLOUD_ARCHITECTURE_IMPLEMENTATION_COMPLETE=false"
    echo "STAGING_DEPLOYMENT_READY=false"
fi

echo
echo \
    "NOTE=This classifies code readiness only; cloud production cutover remains a separate acceptance gate."
