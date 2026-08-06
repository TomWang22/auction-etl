#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(git rev-parse --show-toplevel)"

unset DOCKER_HOST
export DOCKER_CONTEXT='colima'

exec .venv/bin/python \
    scripts/audit_auction_docker_contexts.py \
    "$@"
