#!/usr/bin/env bash
# Auction ETL Postgres backup — auction_warehouse on host port 5544.
#
# Usage:
#   ./scripts/backup-auction-warehouse.sh
#
# Output: output/backups/auction-warehouse-YYYYMMDD-HHMMSS/
#   .dump, .sql.gz, -extensions.tsv, -pg_settings.tsv,
#   -table-counts.tsv, -schemas.tsv, manifest.txt
#
# output/ is gitignored. Do not commit the dumps.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-5544}"
PGUSER="${PGUSER:-auction}"
PGDATABASE="${PGDATABASE:-auction_warehouse}"
export PGPASSWORD="${PGPASSWORD:-${AUCTION_DB_PASSWORD:-auction}}"
TS="${BACKUP_TIMESTAMP:-$(date +%Y%m%d-%H%M%S)}"
BACKUP_BASE="${BACKUP_DIR:-$REPO_ROOT/output/backups}"
OUTDIR="$BACKUP_BASE/auction-warehouse-$TS"
LABEL="${PGPORT}-${PGDATABASE}"
PARALLEL_JOBS="${PG_DUMP_JOBS:-4}"
USE_PG_DOCKER="${USE_PG_DOCKER:-}"

PGHOST_FOR_DOCKER="${PGHOST_FOR_DOCKER:-}"
if [[ -z "$PGHOST_FOR_DOCKER" ]]; then
  if [[ "$PGHOST" == "127.0.0.1" || "$PGHOST" == "localhost" ]]; then
    PGHOST_FOR_DOCKER="host.docker.internal"
  else
    PGHOST_FOR_DOCKER="$PGHOST"
  fi
fi

if ! command -v pg_dump >/dev/null 2>&1 || ! command -v psql >/dev/null 2>&1; then
  if command -v docker >/dev/null 2>&1; then
    USE_PG_DOCKER=1
  else
    echo "pg_dump and psql are required (brew install libpq), or Docker." >&2
    exit 1
  fi
fi

mkdir -p "$OUTDIR"
MANIFEST="$OUTDIR/manifest.txt"
FAILURES=0

# Queries and dumps run in postgres:16-alpine when the host pg_dump
# is missing or older than the server. From inside that container,
# the Mac is host.docker.internal, not 127.0.0.1.
_run_psql() {
  local query="$1"
  docker run --rm \
    -e PGPASSWORD="$PGPASSWORD" \
    postgres:16-alpine \
    psql -h "$PGHOST_FOR_DOCKER" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" \
    -X -P pager=off -Atc "$query"
}

_run_psql_local() {
  local query="$1"
  PGCONNECT_TIMEOUT=5 psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" \
    -X -P pager=off -Atc "$query"
}

_psql() {
  if [[ "${USE_PG_DOCKER}" == "1" ]]; then
    _run_psql "$1"
  else
    _run_psql_local "$1"
  fi
}

{
  echo "Auction ETL Postgres backup — ${PGDATABASE} — $TS"
  echo "Host: ${PGHOST}:${PGPORT}"
  echo "Started: $(date -Iseconds)"
  echo ""
} >"$MANIFEST"

if [[ -z "${USE_PG_DOCKER}" ]] && command -v pg_dump >/dev/null 2>&1; then
  probe_err="$(pg_dump -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -Fc --no-owner -f /dev/null 2>&1 || true)"
  if echo "$probe_err" | grep -q "server version mismatch"; then
    echo "Local pg_dump is older than the server. Using Docker postgres:16-alpine."
    USE_PG_DOCKER=1
  fi
fi

if [[ "${USE_PG_DOCKER}" == "1" ]]; then
  echo "Using Docker (postgres:16-alpine) for pg_dump/psql. Host from the container: ${PGHOST_FOR_DOCKER}"
  echo
fi

identity="$(_psql "SELECT current_database() || '|' || current_user;" || true)"
if [[ "$identity" != "${PGDATABASE}|${PGUSER}" ]]; then
  echo "Unexpected database identity: ${identity:-unavailable}" >&2
  echo "fail identity" >>"$MANIFEST"
  exit 1
fi

echo "=== Auction warehouse backup (${PGHOST}:${PGPORT}/${PGDATABASE}) ==="
echo "Output: $OUTDIR"
echo
# Custom dump restores with pg_restore. The gzipped SQL is the
# readable copy. The TSV files record settings, extensions, tables,
# and live row counts so a restore can be checked without loading it.
echo "Backing up ${LABEL}..."

if [[ "${USE_PG_DOCKER}" == "1" ]]; then
  docker run --rm -e PGPASSWORD="$PGPASSWORD" -v "$OUTDIR:/backup:rw" postgres:16-alpine \
    pg_dump -h "$PGHOST_FOR_DOCKER" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" \
    -Fc -j "$PARALLEL_JOBS" --no-owner --no-privileges -f "/backup/${LABEL}.dump" 2>/dev/null ||
    docker run --rm -e PGPASSWORD="$PGPASSWORD" -v "$OUTDIR:/backup:rw" postgres:16-alpine \
      pg_dump -h "$PGHOST_FOR_DOCKER" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" \
      -Fc --no-owner --no-privileges -f "/backup/${LABEL}.dump"
  docker run --rm -e PGPASSWORD="$PGPASSWORD" -v "$OUTDIR:/backup:rw" postgres:16-alpine \
    sh -c "pg_dump -h $PGHOST_FOR_DOCKER -p $PGPORT -U $PGUSER -d $PGDATABASE -Fp --no-owner --no-privileges | gzip -9 > /backup/${LABEL}.sql.gz"
else
  pg_dump -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" \
    -Fc -j "$PARALLEL_JOBS" --no-owner --no-privileges -f "$OUTDIR/${LABEL}.dump" 2>/dev/null ||
    pg_dump -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" \
    -Fc --no-owner --no-privileges -f "$OUTDIR/${LABEL}.dump"
  pg_dump -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" \
    -Fp --no-owner --no-privileges | gzip -9 >"$OUTDIR/${LABEL}.sql.gz"
fi

_psql "SELECT name||E'\t'||setting||E'\t'||source FROM pg_settings ORDER BY name" >"$OUTDIR/${LABEL}-pg_settings.tsv"
_psql "SELECT extname||E'\t'||extversion FROM pg_extension ORDER BY 1" >"$OUTDIR/${LABEL}-extensions.tsv"
_psql "SELECT schemaname||E'\t'||tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY schemaname, tablename" >"$OUTDIR/${LABEL}-schemas.tsv"
_psql "SELECT schemaname||E'\t'||relname||E'\t'||n_live_tup FROM pg_stat_user_tables ORDER BY schemaname, relname" >"$OUTDIR/${LABEL}-table-counts.tsv"

size_dump="$(ls -lh "$OUTDIR/${LABEL}.dump" 2>/dev/null | awk '{print $5}')"
size_sql="$(ls -lh "$OUTDIR/${LABEL}.sql.gz" 2>/dev/null | awk '{print $5}')"
echo "  ${LABEL}.dump (${size_dump}), ${LABEL}.sql.gz (${size_sql})"
echo "ok ${LABEL} db=${PGDATABASE} ${OUTDIR}/${LABEL}.dump ${OUTDIR}/${LABEL}.sql.gz" >>"$MANIFEST"
echo "Finished: $(date -Iseconds)" >>"$MANIFEST"

for required in \
  "$OUTDIR/${LABEL}.dump" \
  "$OUTDIR/${LABEL}.sql.gz" \
  "$OUTDIR/${LABEL}-pg_settings.tsv" \
  "$OUTDIR/${LABEL}-extensions.tsv" \
  "$OUTDIR/${LABEL}-schemas.tsv" \
  "$OUTDIR/${LABEL}-table-counts.tsv"
do
  if [[ ! -s "$required" ]]; then
    echo "Missing or empty ${required}" >&2
    FAILURES=$((FAILURES + 1))
  fi
done

if [[ "$FAILURES" -gt 0 ]]; then
  echo "Backup validation failed (${FAILURES} issue(s)): $OUTDIR" >&2
  exit 1
fi

echo "Backup complete: $OUTDIR"
echo "Restore: pg_restore --no-owner --no-privileges -d ${PGDATABASE} ${OUTDIR}/${LABEL}.dump"
echo "This folder is under output/ and stays out of git."
