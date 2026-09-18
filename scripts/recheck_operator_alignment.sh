#!/usr/bin/env bash
# Read-only GitHub, Railway, Vercel, and clean-worktree recheck.
# Does not deploy, open Chromium, or write to the warehouse.

set -Eeuo pipefail

ROOT="$(
    cd "$(
        dirname "${BASH_SOURCE[0]}"
    )/.." && pwd
)"
PYTHON="${ROOT}/.venv/bin/python"

cd "${ROOT}" || exit 1

exec "${PYTHON}" \
    scripts/preflight_ebay_operator.py \
    --expected-sha "$(git rev-parse HEAD)" \
    "$@"
