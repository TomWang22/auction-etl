#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${HOME}/auction-etl"
PYTHON="${ROOT}/.venv/bin/python"

APP_HOST="127.0.0.1"
APP_PORT="8501"
APP_URL="http://${APP_HOST}:${APP_PORT}"
APP_HEALTH_URL="${APP_URL}/_stcore/health"

EXPECTED_DB_HOST="127.0.0.1"
EXPECTED_DB_PORT="5544"
EXPECTED_DB_NAME="auction_warehouse"
EXPECTED_DB_USER="auction"

RUNTIME_DIR="${HOME}/.auction-etl/runtime/day-to-day"
LOG_DIR="${ROOT}/logs/day-to-day"
PID_FILE="${RUNTIME_DIR}/collector-review.pid"
APP_LOG="${LOG_DIR}/collector-review.log"

CLOUD_AUDIT=false

if [[ "${1:-}" == "--cloud-audit" ]]; then
    CLOUD_AUDIT=true
elif [[ -n "${1:-}" ]]; then
    printf 'Usage: %s [--cloud-audit]\n' "$0" >&2
    exit 2
fi

section() {
    printf '\n================ %s ================\n\n' "$1"
}

fail() {
    printf '\nERROR: %s\n' "$*" >&2

    cat <<'EOF'

DAY_TO_DAY_LOCAL_GATE=FAIL
DATABASE_WRITE=false
REAL_REFRESH_RUN=false
GIT_PUSH_RUN=false
VERCEL_DEPLOY_RUN=false
RAILWAY_DEPLOY_RUN=false
EOF

    exit 1
}

app_healthy() {
    curl \
        --silent \
        --show-error \
        --fail \
        --max-time 3 \
        "${APP_HEALTH_URL}" \
        >/dev/null 2>&1
}

mkdir -p \
    "${RUNTIME_DIR}" \
    "${LOG_DIR}"

cd "${ROOT}" || exit 1

[[ -x "${PYTHON}" ]] ||
    fail "Project virtual-environment Python is unavailable."

source .venv/bin/activate

section "DAY-TO-DAY POLICY"

echo "LOCAL_APP=${APP_URL}"
echo "LOCAL_DATABASE=${EXPECTED_DB_HOST}:${EXPECTED_DB_PORT}/${EXPECTED_DB_NAME}"
echo "GITHUB_SYNC_ALLOWED=true"
echo "GIT_PUSH_ALLOWED=false"
echo "DATABASE_WRITE_ALLOWED=false"
echo "REAL_REFRESH_ALLOWED=false"
echo "VERCEL_DEPLOY_ALLOWED=false"
echo "RAILWAY_DEPLOY_ALLOWED=false"

section "GIT AND GITHUB ALIGNMENT"

command -v git >/dev/null 2>&1 ||
    fail "git is unavailable."

[[ "$(git branch --show-current)" == "main" ]] ||
    fail "Day-to-day runtime must start from branch main."

PRE_STATUS="$(
    git status \
        --porcelain \
        --untracked-files=all
)"

if [[ -n "${PRE_STATUS}" ]]; then
    printf 'Dirty worktree:\n%s\n' "${PRE_STATUS}" >&2
    fail "Worktree is not clean. Commit, stash, or remove intentional changes first."
fi

git fetch --prune origin main

LOCAL_HEAD="$(git rev-parse HEAD)"
ORIGIN_HEAD="$(git rev-parse origin/main)"

read -r AHEAD_COUNT BEHIND_COUNT <<EOF
$(git rev-list --left-right --count HEAD...origin/main)
EOF

echo "LOCAL_HEAD_BEFORE=${LOCAL_HEAD}"
echo "ORIGIN_MAIN_BEFORE=${ORIGIN_HEAD}"
echo "LOCAL_AHEAD_BY=${AHEAD_COUNT}"
echo "LOCAL_BEHIND_BY=${BEHIND_COUNT}"

case "${AHEAD_COUNT}:${BEHIND_COUNT}" in
    0:0)
        echo "LOCAL_UPDATE_REQUIRED=false"
        ;;

    0:*)
        echo "LOCAL_UPDATE_REQUIRED=true"

        git merge \
            --ff-only \
            origin/main

        echo "LOCAL_FAST_FORWARD=PASS"
        ;;

    *:0)
        fail \
            "Local main contains commits not on GitHub main. Day-to-day mode will not push them."
        ;;

    *)
        fail \
            "Local main and GitHub main diverged. Refusing automatic reconciliation."
        ;;
esac

LOCAL_HEAD="$(git rev-parse HEAD)"
ORIGIN_HEAD="$(git rev-parse origin/main)"

GITHUB_HEAD="$(
    git ls-remote \
        origin \
        refs/heads/main |
        awk 'NR == 1 {print $1}'
)"

[[ -n "${GITHUB_HEAD}" ]] ||
    fail "Could not resolve GitHub main directly."

[[ "${LOCAL_HEAD}" == "${ORIGIN_HEAD}" ]] ||
    fail "Local HEAD does not equal origin/main."

[[ "${LOCAL_HEAD}" == "${GITHUB_HEAD}" ]] ||
    fail "Local HEAD does not equal GitHub main."

FINAL_GIT_STATUS="$(
    git status \
        --porcelain \
        --untracked-files=all
)"

[[ -z "${FINAL_GIT_STATUS}" ]] ||
    fail "Worktree became dirty during GitHub alignment."

echo "LOCAL_HEAD=${LOCAL_HEAD}"
echo "ORIGIN_MAIN=${ORIGIN_HEAD}"
echo "GITHUB_MAIN=${GITHUB_HEAD}"
echo "GITHUB_ALIGNMENT=PASS"
echo "WORKTREE_CLEAN=true"

section "LOCAL DATABASE TARGET"

[[ -n "${DATABASE_URL:-}" ]] ||
    fail \
        "DATABASE_URL is not exported. Export the existing local warehouse URL targeting 127.0.0.1:5544, then rerun."

"${PYTHON}" - <<'PY'
from __future__ import annotations

import os
from urllib.parse import urlsplit

import psycopg

try:
    from scripts.run_latest_auction_refresh import normalize_psycopg_url
except ImportError:
    def normalize_psycopg_url(value: str) -> str:
        return value.replace(
            "postgresql+psycopg://",
            "postgresql://",
            1,
        )


expected_host = "127.0.0.1"
expected_port = 5544
expected_database = "auction_warehouse"
expected_user = "auction"

raw_url = os.environ["DATABASE_URL"]
database_url = normalize_psycopg_url(raw_url)
parts = urlsplit(database_url)

host = parts.hostname or ""
port = parts.port or 5432
database = parts.path.lstrip("/")
user = parts.username or ""

if host not in {"127.0.0.1", "localhost"}:
    raise SystemExit(
        f"ERROR: Day-to-day database host must be local; found {host!r}."
    )

if port != expected_port:
    raise SystemExit(
        f"ERROR: Expected local PostgreSQL port {expected_port}; found {port}."
    )

if database != expected_database:
    raise SystemExit(
        "ERROR: DATABASE_URL database mismatch: "
        f"expected {expected_database!r}, found {database!r}."
    )

if user != expected_user:
    raise SystemExit(
        "ERROR: DATABASE_URL user mismatch: "
        f"expected {expected_user!r}, found {user!r}."
    )

with psycopg.connect(
    database_url,
    connect_timeout=5,
) as connection:
    connection.autocommit = False

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                current_database(),
                current_user,
                inet_server_addr()::text,
                inet_server_port()
            """
        )
        row = cursor.fetchone()

    connection.rollback()

if row is None:
    raise SystemExit(
        "ERROR: Database identity query returned no row."
    )

database_name = str(row[0])
database_user = str(row[1])
server_address = str(row[2])
server_port = int(row[3])

if database_name != expected_database:
    raise SystemExit(
        "ERROR: Connected database identity mismatch: "
        f"{database_name!r}."
    )

if database_user != expected_user:
    raise SystemExit(
        "ERROR: Connected database user mismatch: "
        f"{database_user!r}."
    )

print("DATABASE_TARGET=PASS")
print(f"DATABASE_HOST={host}")
print(f"DATABASE_FORWARD_PORT={port}")
print(f"DATABASE_NAME={database_name}")
print(f"DATABASE_USER={database_user}")
print(f"DATABASE_SERVER_ADDRESS={server_address}")
print(f"DATABASE_SERVER_PORT={server_port}")
print("DATABASE_PASSWORD_PRINTED=false")
print("DATABASE_WRITE=false")
PY

section "LOCAL STREAMLIT"

command -v curl >/dev/null 2>&1 ||
    fail "curl is unavailable."

if app_healthy; then
    echo "STREAMLIT_ALREADY_RUNNING=true"
else
    if command -v lsof >/dev/null 2>&1 &&
        lsof \
            -nP \
            -iTCP:"${APP_PORT}" \
            -sTCP:LISTEN \
            >/dev/null 2>&1; then

        lsof \
            -nP \
            -iTCP:"${APP_PORT}" \
            -sTCP:LISTEN \
            >&2 || true

        fail \
            "Port ${APP_PORT} is occupied, but the Streamlit health endpoint is not healthy."
    fi

    if [[ -s "${PID_FILE}" ]]; then
        OLD_PID="$(cat "${PID_FILE}")"

        if kill -0 "${OLD_PID}" 2>/dev/null; then
            fail \
                "Stored Streamlit PID ${OLD_PID} is alive but the health endpoint is unavailable."
        fi

        rm -f "${PID_FILE}"
    fi

    echo "STREAMLIT_START_REQUIRED=true"

    nohup \
        "${PYTHON}" \
        -m streamlit run \
        app/collector_review.py \
        --server.address "${APP_HOST}" \
        --server.port "${APP_PORT}" \
        --server.headless true \
        >"${APP_LOG}" \
        2>&1 &

    APP_PID="$!"
    printf '%s\n' "${APP_PID}" >"${PID_FILE}"

    READY=false
    ATTEMPT=1

    while [[ "${ATTEMPT}" -le 30 ]]; do
        if app_healthy; then
            READY=true
            break
        fi

        if ! kill -0 "${APP_PID}" 2>/dev/null; then
            printf '\nStreamlit log:\n' >&2
            tail -n 80 "${APP_LOG}" >&2 || true

            fail \
                "Streamlit exited before becoming healthy."
        fi

        sleep 1
        ATTEMPT=$((ATTEMPT + 1))
    done

    if [[ "${READY}" != "true" ]]; then
        printf '\nStreamlit log:\n' >&2
        tail -n 80 "${APP_LOG}" >&2 || true

        fail \
            "Streamlit did not become healthy within 30 seconds."
    fi

    echo "STREAMLIT_STARTED=true"
    echo "STREAMLIT_PID=${APP_PID}"
fi

app_healthy ||
    fail "Streamlit health check failed."

echo "STREAMLIT_HEALTH=PASS"
echo "STREAMLIT_URL=${APP_URL}"
echo "STREAMLIT_LOG=${APP_LOG}"

section "READ-ONLY CLOUD AUDIT"

if [[ "${CLOUD_AUDIT}" != "true" ]]; then
    echo "CLOUD_AUDIT_REQUESTED=false"
    echo "VERCEL_DEPLOY_RUN=false"
    echo "RAILWAY_DEPLOY_RUN=false"
else
    echo "CLOUD_AUDIT_REQUESTED=true"

    if command -v vercel >/dev/null 2>&1; then
        echo
        echo "--- Vercel: read only ---"

        echo "VERCEL_CLI_VERSION=$(vercel --version 2>/dev/null | tail -n 1 || true)"

        if vercel whoami >/dev/null 2>&1; then
            echo "VERCEL_AUTHENTICATION=PASS"
        else
            echo "VERCEL_AUTHENTICATION=UNAVAILABLE"
        fi

        if [[ -s ".vercel/project.json" ]]; then
            VERCEL_PROJECT="$(
                "${PYTHON}" - <<'PY'
from __future__ import annotations

import json
from pathlib import Path


payload = json.loads(
    Path(".vercel/project.json").read_text(
        encoding="utf-8",
    )
)

print(
    str(
        payload.get(
            "projectName",
            "",
        )
    )
)
PY
            )"

            if [[ -n "${VERCEL_PROJECT}" ]]; then
                echo "VERCEL_LINKED_PROJECT=${VERCEL_PROJECT}"

                if vercel project inspect \
                    "${VERCEL_PROJECT}" \
                    >"${LOG_DIR}/vercel-project-inspect.log" \
                    2>&1; then

                    echo "VERCEL_PROJECT_INSPECT=PASS"
                else
                    echo "VERCEL_PROJECT_INSPECT=UNAVAILABLE"
                fi
            else
                echo "VERCEL_LINKED_PROJECT=unknown"
            fi
        else
            echo "VERCEL_LINKED_PROJECT=unavailable"
        fi

        if vercel list \
            >"${LOG_DIR}/vercel-list.log" \
            2>&1; then

            echo "VERCEL_DEPLOYMENT_LIST_QUERY=PASS"
            echo "VERCEL_DEPLOYMENT_LIST_LOG=${LOG_DIR}/vercel-list.log"
        else
            echo "VERCEL_DEPLOYMENT_LIST_QUERY=UNAVAILABLE"
        fi

        echo "VERCEL_DEPLOY_RUN=false"
    else
        echo "VERCEL_CLI=UNAVAILABLE"
        echo "VERCEL_DEPLOY_RUN=false"
    fi

    if command -v railway >/dev/null 2>&1; then
        echo
        echo "--- Railway: read only / deferred runtime ---"

        echo "RAILWAY_CLI_VERSION=$(railway --version 2>/dev/null | tail -n 1 || true)"

        if railway deployment list \
            --limit 1 \
            --json \
            >"${LOG_DIR}/railway-latest.json" \
            2>"${LOG_DIR}/railway-latest.stderr"; then

            echo "RAILWAY_DEPLOYMENT_LIST_QUERY=PASS"

            "${PYTHON}" - \
                "${LOG_DIR}/railway-latest.json" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path


payload = json.loads(
    Path(sys.argv[1]).read_text(
        encoding="utf-8",
    )
)

if isinstance(payload, dict):
    deployments = payload.get(
        "deployments",
        [],
    )
elif isinstance(payload, list):
    deployments = payload
else:
    deployments = []

if not deployments:
    print("RAILWAY_LATEST_DEPLOYMENT=none")
    raise SystemExit(0)

row = deployments[0]

if not isinstance(row, dict):
    print("RAILWAY_LATEST_DEPLOYMENT=unknown")
    raise SystemExit(0)

deployment_id = str(
    row.get("id")
    or row.get("deploymentId")
    or "unknown"
)

status = str(
    row.get("status")
    or row.get("state")
    or "unknown"
)

print(
    f"RAILWAY_LATEST_DEPLOYMENT_ID={deployment_id}"
)
print(
    f"RAILWAY_LATEST_DEPLOYMENT_STATUS={status}"
)
PY
        else
            echo "RAILWAY_DEPLOYMENT_LIST_QUERY=UNAVAILABLE"
            echo "RAILWAY_NOTE=Railway is deferred and is not required for local day-to-day operation."
        fi

        echo "RAILWAY_DEPLOY_RUN=false"
    else
        echo "RAILWAY_CLI=UNAVAILABLE"
        echo "RAILWAY_DEPLOY_RUN=false"
    fi
fi

section "FINAL GATE"

git fetch --prune origin main

FINAL_LOCAL_HEAD="$(git rev-parse HEAD)"
FINAL_ORIGIN_HEAD="$(git rev-parse origin/main)"

FINAL_GITHUB_HEAD="$(
    git ls-remote \
        origin \
        refs/heads/main |
        awk 'NR == 1 {print $1}'
)"

FINAL_STATUS="$(
    git status \
        --porcelain \
        --untracked-files=all
)"

[[ "${FINAL_LOCAL_HEAD}" == "${FINAL_ORIGIN_HEAD}" ]] ||
    fail "Local HEAD changed relative to origin/main."

[[ "${FINAL_LOCAL_HEAD}" == "${FINAL_GITHUB_HEAD}" ]] ||
    fail "Local HEAD changed relative to GitHub main."

[[ -z "${FINAL_STATUS}" ]] ||
    fail "Worktree is no longer clean."

app_healthy ||
    fail "Streamlit is no longer healthy."

cat <<EOF

DAY_TO_DAY_LOCAL_GATE=PASS

LOCAL_HEAD=${FINAL_LOCAL_HEAD}
ORIGIN_MAIN=${FINAL_ORIGIN_HEAD}
GITHUB_MAIN=${FINAL_GITHUB_HEAD}

GITHUB_ALIGNMENT=PASS
WORKTREE_CLEAN=true

LOCAL_APP=${APP_URL}
LOCAL_APP_HEALTH=PASS

LOCAL_DATABASE=${EXPECTED_DB_HOST}:${EXPECTED_DB_PORT}/${EXPECTED_DB_NAME}
DATABASE_TARGET=PASS

DATABASE_WRITE=false
REAL_REFRESH_RUN=false

GIT_PUSH_RUN=false
VERCEL_DEPLOY_RUN=false
RAILWAY_DEPLOY_RUN=false

DAY_TO_DAY_RUNTIME=LOCAL_ONLY
READY_FOR_DAY_TO_DAY_USE=true

NEXT_ACTION=Use ${APP_URL}. Deployments remain explicit release operations only.
EOF
