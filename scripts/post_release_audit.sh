#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(
    cd "$(
        dirname "${BASH_SOURCE[0]}"
    )/.." &&
        pwd
)"

EXPECTED_PRODUCTION_COMMIT='9adf009c698d7448a58d280186fc1f3cd16e9644'
EXPECTED_PRODUCTION_TAG='production-incremental-20260818-9adf009'

REMOTE="${AUCTION_GIT_REMOTE:-origin}"

STREAMLIT_URL="${AUCTION_STREAMLIT_HEALTH_URL:-http://127.0.0.1:8501/_stcore/health}"

DEFAULT_DATABASE_URL='postgresql+psycopg://auction:auction@127.0.0.1:5544/auction_warehouse'
AUDIT_DATABASE_URL="${DATABASE_URL:-${DEFAULT_DATABASE_URL}}"

RUN_TESTS=false
REQUIRE_BUYEE_OWNER=false


fail() {
    printf '\nERROR: %s\n' "$1" >&2
    exit 1
}


for argument in "$@"; do
    case "${argument}" in
        --tests)
            RUN_TESTS=true
            ;;

        --require-buyee-owner)
            REQUIRE_BUYEE_OWNER=true
            ;;

        *)
            printf \
                'Unknown option: %s\n' \
                "${argument}" >&2
            exit 2
            ;;
    esac
done


PYTHON="${ROOT}/.venv/bin/python3"

if [[ ! -x "${PYTHON}" ]]; then
    PYTHON="${ROOT}/.venv/bin/python"
fi

[[ -x "${PYTHON}" ]] ||
    fail \
        "Project Python is unavailable."


cd "${ROOT}"


echo "================================================================"
echo "POST-RELEASE PRODUCTION AUDIT"
echo "================================================================"


git fetch \
    --prune \
    "${REMOTE}"

local_main="$(
    git rev-parse \
        refs/heads/main
)"

origin_main="$(
    git rev-parse \
        "${REMOTE}/main"
)"

tag_commit="$(
    git rev-list \
        -n 1 \
        "${EXPECTED_PRODUCTION_TAG}"
)"

[[ "${local_main}" == "${EXPECTED_PRODUCTION_COMMIT}" ]] ||
    fail \
        "Local main moved from validated production."

[[ "${origin_main}" == "${EXPECTED_PRODUCTION_COMMIT}" ]] ||
    fail \
        "origin/main moved from validated production."

[[ "${tag_commit}" == "${EXPECTED_PRODUCTION_COMMIT}" ]] ||
    fail \
        "Production tag moved from validated production."

echo "LOCAL_MAIN=${local_main}"
echo "ORIGIN_MAIN=${origin_main}"
echo "PRODUCTION_TAG_COMMIT=${tag_commit}"
echo "GIT_PRODUCTION_IDENTITY=PASS"


echo
echo "----------------------------------------------------------------"
echo "Protected local files"
echo "----------------------------------------------------------------"

"${PYTHON}" - \
    "${ROOT}" <<'PY'
from __future__ import annotations

import hashlib
import sys
from pathlib import Path


root = Path(sys.argv[1])

expected = {
    ".env.auction-etl.private": (
        165,
        "fd3604acaa7ad60f7d9b54ed3a0ca4187b9ce429d8261b8ea991137076cd61a1",
    ),
    "recovery-input/auction_report_buyee_no_bulk.csv": (
        27445,
        "5f9ba13a6c52f7637be77c5885416cb26244ddc315cee58852af530849605cc4",
    ),
    "recovery-input/auction_report_ebay_facerecords_no_bulk_completed.csv": (
        20679,
        "a022c651ed3b7074732218b4328f91e2385c695192a964ee890840be5b9ca76b",
    ),
    "recovery-input/auction_report_ebay_no_bulk_completed.csv": (
        201016,
        "5fee0513977ba5a4e9b73bad193caafb986ed2fb02ccf7f54b6c8028ac020ab3",
    ),
}

for relative, (
    expected_size,
    expected_hash,
) in expected.items():
    path = root / relative

    if not path.is_file():
        raise SystemExit(
            f"Protected file missing: {relative}"
        )

    digest = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()

    actual_size = path.stat().st_size

    if actual_size != expected_size:
        raise SystemExit(
            f"Protected file size changed: {relative}"
        )

    if digest != expected_hash:
        raise SystemExit(
            f"Protected file hash changed: {relative}"
        )

    print(
        f"PRIVATE_FILE={relative}"
    )

print(
    f"PRIVATE_FILE_COUNT={len(expected)}"
)
print(
    "PRIVATE_FILES_HASH_VERIFIED=true"
)
PY


echo
echo "----------------------------------------------------------------"
echo "Runtime"
echo "----------------------------------------------------------------"

health="$(
    curl \
        --fail \
        --silent \
        --show-error \
        --max-time 5 \
        "${STREAMLIT_URL}"
)"

[[ "${health}" == "ok" ]] ||
    fail \
        "Streamlit health endpoint did not return ok."

active_ingestion="$(
    ps -axo pid=,command= |
        grep -E \
            'run_auction_refresh_on_demand\.sh|run_latest_auction_refresh\.py|run_multisource_ingestion_round\.py' |
        grep -v grep ||
        true
)"

if [[ -n "${active_ingestion}" ]]; then
    printf '%s\n' \
        "${active_ingestion}" >&2

    fail \
        "Marketplace ingestion is active."
fi

owner_rows="$(
    ps -axo pid=,command= |
        grep -E \
            '/scripts/run_buyee_owner\.py' |
        grep -v grep ||
        true
)"

owner_count="$(
    printf '%s\n' \
        "${owner_rows}" |
        grep -c . ||
        true
)"

if "${REQUIRE_BUYEE_OWNER}"; then
    [[ "${owner_count}" == "1" ]] ||
        fail \
            "Expected exactly one Buyee owner; found ${owner_count}."
fi

echo "STREAMLIT_HTTP_HEALTH=PASS"
echo "ACTIVE_INGESTION_PROCESS_COUNT=0"
echo "BUYEE_OWNER_PROCESS_COUNT=${owner_count}"


echo
echo "----------------------------------------------------------------"
echo "Database read-only check"
echo "----------------------------------------------------------------"

AUDIT_DATABASE_URL="${AUDIT_DATABASE_URL}" \
"${PYTHON}" - <<'PY'
from __future__ import annotations

import os

from sqlalchemy import create_engine, text


url = os.environ[
    "AUDIT_DATABASE_URL"
]

if url.startswith(
    "postgresql://"
):
    url = url.replace(
        "postgresql://",
        "postgresql+psycopg://",
        1,
    )

engine = create_engine(
    url,
    pool_pre_ping=True,
    future=True,
)

with engine.connect() as connection:
    transaction = connection.begin()

    try:
        connection.execute(
            text(
                "SET TRANSACTION READ ONLY"
            )
        )

        row = connection.execute(
            text(
                """
                SELECT
                    current_database()
                        AS database_name,
                    current_user
                        AS database_user,
                    COUNT(*)
                        AS auction_rows
                FROM warehouse.auction
                """
            )
        ).mappings().one()

        transaction.rollback()
    except Exception:
        transaction.rollback()
        raise

print(
    f"DATABASE_NAME={row['database_name']}"
)
print(
    f"DATABASE_USER={row['database_user']}"
)
print(
    f"WAREHOUSE_AUCTION_ROWS={row['auction_rows']}"
)
print(
    "DATABASE_TRANSACTION_READ_ONLY=true"
)
print(
    "DATABASE_READ_CHECK=PASS"
)
PY


DATABASE_URL="${AUDIT_DATABASE_URL}" \
"${PYTHON}" \
    -m alembic current

echo "ALEMBIC_CURRENT_CHECK=PASS"


if "${RUN_TESTS}"; then
    echo
    echo "----------------------------------------------------------------"
    echo "Canonical tests"
    echo "----------------------------------------------------------------"

    env \
        PYTHONPATH="${ROOT}" \
        PYTHONDONTWRITEBYTECODE=1 \
        PYTHONNOUSERSITE=1 \
        PYTHONUNBUFFERED=1 \
        "${PYTHON}" \
            -m pytest \
            -q \
            -p no:cacheprovider \
            tests

    echo "CANONICAL_TEST_SUITE=PASS"
fi


echo
echo "================================================================"
echo "RESULT=POST_RELEASE_AUDIT_PASS"
echo "================================================================"
