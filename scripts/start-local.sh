#!/usr/bin/env bash
# One command for local Collector Review.
#
# Brings up the existing Colima Postgres on 127.0.0.1:5544 if it is down,
# then keeps https://localhost:8501 up. If Streamlit exits, this starts it
# again. It does not create a database, volume, or container.
#
# Usage:
#   ./scripts/start-local.sh
#   ./scripts/start-local.sh --foreground

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

APP_HOST="127.0.0.1"
APP_PORT="8501"
APP_URL="https://localhost:${APP_PORT}"
HEALTH_URL="${APP_URL}/_stcore/health"

DB_HOST="127.0.0.1"
DB_PORT="5544"
DB_NAME="auction_warehouse"
DB_USER="auction"
DB_PASSWORD="${AUCTION_DB_PASSWORD:-auction}"

DOCKER_CONTEXT_NAME="${DOCKER_CONTEXT_NAME:-colima}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-auction-etl}"
DATABASE_SERVICE="${AUCTION_DATABASE_SERVICE:-db}"
PREFERRED_CONTAINER="${AUCTION_DB_CONTAINER:-auction-etl-db-1}"

LOG_DIR="${REPO_ROOT}/logs/collector-ui"
LOG_PATH="${LOG_DIR}/start-local.log"
PID_PATH="${LOG_DIR}/start-local.pid"
CERT_FILE="${REPO_ROOT}/.streamlit/certs/localhost.pem"
KEY_FILE="${REPO_ROOT}/.streamlit/certs/localhost-key.pem"

export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}}"
export AUCTION_ENV="${AUCTION_ENV:-development}"
export OIDC_ENV="${OIDC_ENV:-development}"
export OIDC_REDIRECT_URI="${OIDC_REDIRECT_URI:-https://localhost:8501/oauth2callback}"
export PGPASSWORD="${DB_PASSWORD}"
export PYTHONUNBUFFERED=1

FOREGROUND=0
if [[ "${1:-}" == "--foreground" ]]; then
  FOREGROUND=1
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--foreground]" >&2
  exit 2
fi

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

# pg_isready against the existing warehouse. A refused connection means
# the container is stopped, not that a new database should be created.
postgres_ready() {
  pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1
}

# HTTPS health check. --insecure accepts the local mkcert certificate
# even when curl's trust store does not.
app_ready() {
  curl --silent --fail --max-time 3 --insecure "$HEALTH_URL" >/dev/null 2>&1
}

port_busy() {
  lsof -nP -iTCP:"$APP_PORT" -sTCP:LISTEN >/dev/null 2>&1
}

docker_cmd() {
  docker --context "$DOCKER_CONTEXT_NAME" "$@"
}

# Prefer the known container name. Fall back to the compose service
# label only when exactly one container matches. Never create one.
find_database_container() {
  local id name
  local candidates=()
  while IFS= read -r id; do
    [[ -n "$id" ]] || continue
    name="$(docker_cmd inspect --format '{{.Name}}' "$id" | sed 's#^/##')"
    if [[ "$name" == "$PREFERRED_CONTAINER" ]]; then
      printf '%s\n' "$id"
      return 0
    fi
    candidates+=("$id")
  done < <(docker_cmd ps -aq --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME}" --filter "label=com.docker.compose.service=${DATABASE_SERVICE}")

  if [[ "${#candidates[@]}" -eq 1 ]]; then
    printf '%s\n' "${candidates[0]}"
    return 0
  fi
  if [[ "${#candidates[@]}" -gt 1 ]]; then
    fail "More than one ${COMPOSE_PROJECT_NAME}/${DATABASE_SERVICE} container exists. Nothing was started."
  fi
  return 1
}

# Start Colima and the existing Postgres container when port 5544 is down.
# A wrong host port is left alone so a second database is not published.
ensure_postgres() {
  if postgres_ready; then
    echo "Postgres is already up on ${DB_HOST}:${DB_PORT}/${DB_NAME}."
    return 0
  fi

  command -v colima >/dev/null 2>&1 || fail "Colima is not installed, and Postgres on port ${DB_PORT} is down."
  command -v docker >/dev/null 2>&1 || fail "Docker CLI is not installed, and Postgres on port ${DB_PORT} is down."

  if ! colima status >/dev/null 2>&1; then
    echo "Starting Colima..."
    colima start
  fi

  docker context inspect "$DOCKER_CONTEXT_NAME" >/dev/null 2>&1 ||
    fail "Docker context ${DOCKER_CONTEXT_NAME} does not exist."

  local container_id container_name binding host_port running attempt
  container_id="$(find_database_container || true)"
  [[ -n "$container_id" ]] || {
    echo "Existing ${PREFERRED_CONTAINER} was not found. Nothing was created." >&2
    return 1
  }

  container_name="$(docker_cmd inspect --format '{{.Name}}' "$container_id" | sed 's#^/##')"
  binding="$(
    docker_cmd inspect --format '{{with index .NetworkSettings.Ports "5432/tcp"}}{{range .}}{{.HostPort}}{{println}}{{end}}{{end}}' "$container_id" |
      awk 'NF {print; exit}'
  )"
  host_port="${binding:-}"
  [[ "$host_port" == "$DB_PORT" ]] || {
    echo "Container ${container_name} publishes Postgres on ${host_port:-none}, not ${DB_PORT}. It was not recreated." >&2
    return 1
  }

  running="$(docker_cmd inspect --format '{{.State.Running}}' "$container_id")"
  if [[ "$running" != "true" ]]; then
    echo "Starting existing database container ${container_name}..."
    docker_cmd start "$container_id" >/dev/null
  fi

  for attempt in $(seq 1 60); do
    if postgres_ready; then
      echo "Postgres is up on ${DB_HOST}:${DB_PORT}/${DB_NAME}."
      return 0
    fi
    sleep 1
  done

  docker_cmd logs --tail 80 "$container_id" || true
  echo "Postgres on port ${DB_PORT} did not become ready." >&2
  return 1
}

# Refuse to watch a process that is pointed at some other database.
verify_identity() {
  local identity
  identity="$(
    psql "postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}" \
      -At -v ON_ERROR_STOP=1 \
      -c "SELECT current_database() || '|' || current_user;"
  )"
  [[ "$identity" == "${DB_NAME}|${DB_USER}" ]] ||
    fail "Unexpected database identity: ${identity:-unavailable}"
}

# Yahoo's redirect is https://localhost:8501/oauth2callback, so the
# app is served with the mkcert pair under .streamlit/certs.
ensure_certs() {
  if [[ -f "$CERT_FILE" && -f "$KEY_FILE" ]]; then
    return 0
  fi
  command -v mkcert >/dev/null 2>&1 ||
    fail "TLS certs are missing at .streamlit/certs and mkcert is not installed."
  mkdir -p "${REPO_ROOT}/.streamlit/certs"
  mkcert -install
  mkcert \
    -cert-file "$CERT_FILE" \
    -key-file "$KEY_FILE" \
    localhost 127.0.0.1 ::1
}

run_streamlit() {
  set +u
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.venv/bin/activate"
  set -u
  python -m streamlit run app/collector_review.py \
    --server.address "$APP_HOST" \
    --server.port "$APP_PORT" \
    --server.headless true \
    --server.sslCertFile "$CERT_FILE" \
    --server.sslKeyFile "$KEY_FILE" \
    --browser.gatherUsageStats false
}

# Stay up. If Postgres drops, start the existing container again.
# If Streamlit exits and port 8501 is free, start it again.
# A foreign process already bound to 8501 is not killed.
supervise() {
  cd "$REPO_ROOT"
  while true; do
    if ! postgres_ready; then
      echo "$(date -Iseconds) Postgres is down. Bringing the existing database back."
      if ! ensure_postgres; then
        sleep 5
        continue
      fi
    fi

    if app_ready; then
      sleep 5
      continue
    fi

    if port_busy; then
      echo "$(date -Iseconds) Port ${APP_PORT} is busy and the app is not healthy. Leaving that process alone."
      sleep 5
      continue
    fi

    echo "$(date -Iseconds) Starting Collector Review at ${APP_URL}"
    set +e
    run_streamlit
    local status=$?
    set -e
    echo "$(date -Iseconds) Collector Review exited (${status}). Starting it again."
    sleep 2
  done
}

supervisor_alive() {
  [[ -f "$PID_PATH" ]] || return 1
  local pid
  pid="$(cat "$PID_PATH" 2>/dev/null || true)"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

mkdir -p "$LOG_DIR"
[[ -x "${REPO_ROOT}/.venv/bin/python" ]] || fail "Project virtualenv is missing at .venv."

echo "Auction ETL local start"
echo "Database: ${DB_HOST}:${DB_PORT}/${DB_NAME}"
echo "App:      ${APP_URL}"

ensure_postgres || exit 1
verify_identity
ensure_certs

if [[ "$FOREGROUND" -eq 1 ]]; then
  echo "Watching in the foreground. Ctrl-C stops the watcher."
  supervise
  exit 0
fi

if supervisor_alive; then
  echo "Watcher is already running (pid $(cat "$PID_PATH"))."
else
  nohup "$0" --foreground >>"$LOG_PATH" 2>&1 &
  echo $! >"$PID_PATH"
  echo "Watcher pid: $(cat "$PID_PATH")"
  echo "Log: ${LOG_PATH}"
fi

ready=0
for _ in $(seq 1 90); do
  if app_ready; then
    ready=1
    break
  fi
  sleep 1
done

if [[ "$ready" -ne 1 ]]; then
  echo "Collector Review did not answer ${HEALTH_URL}." >&2
  echo "Log: ${LOG_PATH}" >&2
  tail -80 "$LOG_PATH" >&2 || true
  exit 1
fi

echo "Collector Review is up: ${APP_URL}"
echo "If Streamlit or Postgres stops, the watcher starts them again."
