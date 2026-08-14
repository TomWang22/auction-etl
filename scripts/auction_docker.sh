#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ROOT="$(
    cd "$(dirname "${BASH_SOURCE[0]}")/.." &&
        pwd
)"

RUNTIME_ENV="${PROJECT_ROOT}/.auction-etl-runtime.env"

if [[ ! -f "${RUNTIME_ENV}" ]]; then
    echo "ERROR: Missing ${RUNTIME_ENV}" >&2
    exit 1
fi

# shellcheck disable=SC1090
source "${RUNTIME_ENV}"

if [[ "${AUCTION_DOCKER_CONTEXT:-}" == "colima" ]]; then
    echo "ERROR: Auction ETL cannot use Colima." >&2
    exit 1
fi

exec docker \
    --context "${AUCTION_DOCKER_CONTEXT}" \
    "$@"
