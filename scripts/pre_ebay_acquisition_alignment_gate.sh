#!/usr/bin/env bash
# Pre-acquisition GitHub/Railway/Vercel alignment gate.
# Does not commit, push, or deploy.
# Acquisition runs only when RUN_OPERATOR=1.
# --apply writes only when NEW_IDENTITY_COUNT>0.

set -Eeuo pipefail

ROOT="$(
    cd "$(
        dirname "${BASH_SOURCE[0]}"
    )/.." && pwd
)"
PYTHON="${ROOT}/.venv/bin/python"

OPERATOR='scripts/run_ebay_external_handoff.py'
STATE_FILE="${AUCTION_LOCAL_EBAY_STATE_FILE:-${HOME}/.auction-etl/private/ebay-storage-state.json}"
EXPECTED_DATABASE_NAME="${AUCTION_EXPECTED_DATABASE_NAME:-auction_warehouse}"
EXPECTED_DATABASE_USER="${AUCTION_EXPECTED_DATABASE_USER:-auction}"
RUN_OPERATOR="${RUN_OPERATOR:-0}"

cd "${ROOT}" || exit 1
source .venv/bin/activate

EXPECTED_RELEASE="${EXPECTED_RELEASE:-$(git rev-parse HEAD)}"

echo
echo "================ PRE-ACQUISITION ALIGNMENT GATE ================"
echo "PINNED_RELEASE=${EXPECTED_RELEASE}"
echo "RUN_OPERATOR=${RUN_OPERATOR}"
echo "RAILWAY_DEPLOY_RUN=false"
echo "VERCEL_DEPLOY_RUN=false"
echo "GIT_COMMIT_CREATED=false"
echo "GIT_PUSH_RUN=false"

[[ "$(git branch --show-current)" == "main" ]] || {
    echo "ERROR: local branch is not main." >&2
    exit 1
}

git fetch --prune origin main

LOCAL_HEAD="$(git rev-parse HEAD)"
ORIGIN_HEAD="$(git rev-parse origin/main)"
GITHUB_HEAD="$(
    git ls-remote origin refs/heads/main |
        awk 'NR == 1 {print $1}'
)"

printf 'LOCAL_HEAD=%s\n' "${LOCAL_HEAD}"
printf 'ORIGIN_MAIN=%s\n' "${ORIGIN_HEAD}"
printf 'GITHUB_MAIN=%s\n' "${GITHUB_HEAD}"

[[ "${LOCAL_HEAD}" == "${EXPECTED_RELEASE}" ]] || {
    echo "ERROR: local HEAD is not the pinned release." >&2
    exit 1
}
[[ "${ORIGIN_HEAD}" == "${EXPECTED_RELEASE}" ]] || {
    echo "ERROR: origin/main is not the pinned release." >&2
    exit 1
}
[[ "${GITHUB_HEAD}" == "${EXPECTED_RELEASE}" ]] || {
    echo "ERROR: GitHub main is not the pinned release." >&2
    exit 1
}

git diff --quiet HEAD -- || {
    echo "ERROR: tracked worktree is dirty." >&2
    exit 1
}
git diff --cached --quiet || {
    echo "ERROR: staged changes exist." >&2
    exit 1
}
[[ -z "$(git status --porcelain --untracked-files=all)" ]] || {
    echo "ERROR: worktree is not clean." >&2
    git status --porcelain --untracked-files=all >&2
    exit 1
}

[[ -x "${PYTHON}" ]] || {
    echo "ERROR: project Python is unavailable." >&2
    exit 1
}
[[ -f "${OPERATOR}" ]] || {
    echo "ERROR: external-handoff operator is unavailable." >&2
    exit 1
}

"${PYTHON}" \
    scripts/preflight_ebay_operator.py \
    --expected-sha "${EXPECTED_RELEASE}"

echo
echo "PRE_ACQUISITION_ALIGNMENT_GATE=PASS"
echo "READY_FOR_NEXT_EBAY_ACQUISITION=true"

if [[ "${RUN_OPERATOR}" != "1" ]]; then
    echo "OPERATOR_RUN=false"
    echo "NEXT_ACTION=Re-run with RUN_OPERATOR=1 only when you want a headed eBay window."
    exit 0
fi

[[ -n "${DATABASE_URL:-}" ]] || {
    echo "ERROR: DATABASE_URL must be explicitly exported before acquisition." >&2
    exit 1
}
[[ -s "${STATE_FILE}" ]] || {
    echo "ERROR: eBay storage-state file is unavailable." >&2
    exit 1
}

unset RAILWAY_ENVIRONMENT || true
unset RAILWAY_ENVIRONMENT_ID || true
unset RAILWAY_PROJECT_ID || true
unset RAILWAY_SERVICE_ID || true
unset RAILWAY_REPLICA_ID || true

echo
echo "================ EXTERNAL EBAY OPERATOR ================"
echo "NOTICE=A headed Chromium window will open."
echo "NOTICE=Do not manually sign in, solve challenges, or alter browser state."
echo "NOTICE=--apply writes only when NEW_IDENTITY_COUNT>0."
echo "DATABASE_URL_EXPLICIT=true"
echo "DATABASE_PASSWORD_PRINTED=false"

TIMESTAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
mkdir -p "${ROOT}/logs"
LOG_FILE="${ROOT}/logs/ebay-external-operator-${TIMESTAMP}.log"

set +e
"${PYTHON}" "${OPERATOR}" \
    --storage-state "${STATE_FILE}" \
    --database-url "${DATABASE_URL}" \
    --expected-database-name "${EXPECTED_DATABASE_NAME}" \
    --expected-database-user "${EXPECTED_DATABASE_USER}" \
    --max-pages 2 \
    --apply \
    --confirm-write \
    2>&1 | tee "${LOG_FILE}"
OPERATOR_EXIT="${PIPESTATUS[0]}"
set -e

echo "OPERATOR_LOG=${LOG_FILE}"
echo "EBAY_EXTERNAL_OPERATOR_EXIT=${OPERATOR_EXIT}"
[[ "${OPERATOR_EXIT}" -eq 0 ]]
echo "EBAY_EXTERNAL_OPERATOR_GATE=PASS"
