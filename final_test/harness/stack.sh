#!/usr/bin/env bash
# One command to run the whole final-test stack. Safe to re-run. Never prints secrets.
#
#   final_test/harness/stack.sh up [production|local]   start everything (default: production + ngrok tunnel)
#   final_test/harness/stack.sh down [--all]            stop API, tunnel, proxy (--all also stops Postgres)
#   final_test/harness/stack.sh status                  what is up, with health checks
#   final_test/harness/stack.sh snapshot NAME           save the database to ~/bb_snapshots/NAME.dump
#   final_test/harness/stack.sh restore NAME            replace the database with a snapshot (stops the API first)
#   final_test/harness/stack.sh logs [api|ngrok]        tail a log
#
# Variables (all optional):  ENV_FILE=~/final_test.env  API_PORT=8000  PROXY_PORT=8081  PG_PORT=5432
#   DB_NAME=builder  PG_NAME=bb-final-pg  CADDY_NAME=bb-final-caddy-<proxy port>  TUNNEL=1|0  REBUILD=1 (force frontend build)
#   MAIL=sink      send app mail to a local Mailpit (API http://127.0.0.1:8025) instead of the real GoDaddy mailbox
#   STACK_SET="K=V K2=V2"   extra BUILDER_* overrides for the API (no spaces inside values)
# The browser origin is the proxy (http://localhost:$PROXY_PORT in local mode, the ngrok https URL in production mode).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$HOME/final_test.env}"
API_PORT="${API_PORT:-8000}"; PROXY_PORT="${PROXY_PORT:-8081}"; PG_PORT="${PG_PORT:-5432}"
DB_NAME="${DB_NAME:-builder}"; PG_NAME="${PG_NAME:-bb-final-pg}"; CADDY_NAME="${CADDY_NAME:-bb-final-caddy-${PROXY_PORT}}"
RUN="$ROOT/final_test/run"; LOGS="$ROOT/final_test/logs"; SNAP="$HOME/bb_snapshots"
WITH_ENV="python3 $ROOT/final_test/credentials/with_env.py $ENV_FILE"
mkdir -p "$RUN" "$LOGS" "$SNAP"; chmod 700 "$SNAP"

envval() { python3 - "$ROOT" "$ENV_FILE" "$1" <<'PY'
import sys
sys.path.insert(0, sys.argv[1] + "/final_test/credentials")
from pathlib import Path
from check_env import load_env
print(load_env(Path(sys.argv[2]).expanduser()).get(sys.argv[3], ""))
PY
}

host_of() { echo "$1" | sed -E 's#^https?://([^/]+).*#\1#'; }

overrides() {  # prints "-s K=V" pairs for the chosen mode
  local mode="$1" db="postgresql+asyncpg://builder_app:builder_app@127.0.0.1:${PG_PORT}/${DB_NAME}"
  local owner="postgresql+asyncpg://builder:builder@127.0.0.1:${PG_PORT}/${DB_NAME}"
  # SEC M-1: the API connects as the non-superuser role; only Alembic uses the owner.
  printf -- '-s\nBUILDER_DATABASE_URL=%s\n-s\nBUILDER_MIGRATIONS_DATABASE_URL=%s\n' "$db" "$owner"
  if [ "${MAIL:-real}" = sink ]; then
    printf -- '-s\nBUILDER_SMTP_HOST=127.0.0.1\n-s\nBUILDER_SMTP_PORT=1025\n-s\nBUILDER_SMTP_STARTTLS=false\n-s\nBUILDER_SMTP_USERNAME=\n-s\nBUILDER_SMTP_PASSWORD=\n'
  fi
  for kv in ${STACK_SET:-}; do printf -- '-s\n%s\n' "$kv"; done
  if [ "$mode" = local ]; then
    local o="http://localhost:${PROXY_PORT}"
    printf -- '-s\nBUILDER_ENVIRONMENT=local\n-s\nBUILDER_PUBLIC_APP_URL=%s\n-s\nBUILDER_PUBLIC_API_URL=%s\n-s\nBUILDER_CORS_ORIGINS=["%s"]\n-s\nBUILDER_TRUST_PROXY_HEADERS=false\n' "$o" "$o" "$o"
  fi
}

run_env() {  # run_env MODE -- cmd...
  local mode="$1"; shift; shift
  mapfile -t ov < <(overrides "$mode")
  $WITH_ENV "${ov[@]}" -- "$@"
}

origin_for() { [ "$1" = local ] && echo "http://localhost:${PROXY_PORT}" || envval FINAL_TEST_TUNNEL_API_URL; }

wait_http() { local url="$1" n=0; until curl -fs -o /dev/null -H 'ngrok-skip-browser-warning: 1' "$url"; do n=$((n+1)); [ $n -gt 40 ] && return 1; sleep 1; done; }

ensure_pg() {
  if ! docker ps -a --format '{{.Names}}' | grep -qx "$PG_NAME"; then
    docker run -d --name "$PG_NAME" -e POSTGRES_USER=builder -e POSTGRES_PASSWORD=builder -e POSTGRES_DB=builder \
      -p "127.0.0.1:${PG_PORT}:5432" postgres:16-alpine >/dev/null
  else
    docker start "$PG_NAME" >/dev/null 2>&1 || true
  fi
  local n=0; until docker exec "$PG_NAME" pg_isready -U builder -d builder >/dev/null 2>&1; do n=$((n+1)); [ $n -gt 40 ] && { echo "postgres not ready"; exit 1; }; sleep 1; done
  if ! docker exec "$PG_NAME" psql -U builder -d postgres -Atc "select 1 from pg_database where datname='${DB_NAME}'" | grep -q 1; then
    docker exec "$PG_NAME" psql -U builder -d postgres -c "create database \"${DB_NAME}\"" >/dev/null
  fi
  # least-privilege API role (idempotent; per database because default privileges are per database)
  docker exec -i "$PG_NAME" psql -q -U builder -d "$DB_NAME" <"$ROOT/scripts/db/10-app-role.sql" >/dev/null
}

stop_api() { [ -f "$RUN/api.pid" ] && kill "$(cat "$RUN/api.pid")" 2>/dev/null || true; pkill -f "uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}" 2>/dev/null || true; rm -f "$RUN/api.pid"; }

cmd_up() {
  local mode="${1:-production}"; [ -f "$ENV_FILE" ] || { echo "env file $ENV_FILE not found"; exit 1; }
  echo "mode=$mode  api=:$API_PORT  proxy=:$PROXY_PORT  postgres=:$PG_PORT/$DB_NAME"
  ensure_pg
  if [ "${MAIL:-real}" = sink ]; then
    docker ps -a --format '{{.Names}}' | grep -qx bb-final-mailpit || docker run -d --name bb-final-mailpit -p 127.0.0.1:1025:1025 -p 127.0.0.1:8025:8025 axllent/mailpit >/dev/null
    docker start bb-final-mailpit >/dev/null 2>&1 || true
  fi
  ( cd "$ROOT" && run_env "$mode" -- uv run alembic upgrade head >"$LOGS/alembic.log" 2>&1 </dev/null ) || { echo "migration failed, see final_test/logs/alembic.log"; exit 1; }
  # frontend build, one directory per mode+origin so nothing is stale
  local origin; origin="$(origin_for "$mode")"; local tag; tag="$(echo "$mode-$origin" | tr -c 'A-Za-z0-9\n' _)"
  local dist="$RUN/dist-$tag"
  if [ ! -d "$dist" ] || [ "${REBUILD:-0}" = 1 ]; then
    echo "building frontend for $origin"
    ( cd "$ROOT/frontend" && VITE_API_BASE_URL="$origin" npm run build -- --outDir "$dist" --emptyOutDir >"$LOGS/frontend_build.log" 2>&1 ) || { echo "frontend build failed, see final_test/logs/frontend_build.log"; exit 1; }
  fi
  # one origin for app + API (SameSite=Strict refresh cookie): static files from dist, everything else to the API
  cat >"$RUN/Caddyfile" <<EOF
{
	admin off
	auto_https off
}
:${PROXY_PORT} {
	@static {
		path / /assets/* /favicon.svg /index.html
	}
	handle @static {
		root * /srv
		file_server
	}
	handle {
		reverse_proxy 127.0.0.1:${API_PORT}
	}
}
EOF
  docker rm -f "$CADDY_NAME" >/dev/null 2>&1 || true
  docker run -d --name "$CADDY_NAME" --network host -v "$RUN/Caddyfile:/etc/caddy/Caddyfile:ro" -v "$dist:/srv:ro" caddy:2-alpine >/dev/null
  stop_api
  mapfile -t ov < <(overrides "$mode")
  cd "$ROOT"
  setsid nohup $WITH_ENV "${ov[@]}" -- uv run uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" >"$LOGS/api.log" 2>&1 </dev/null &
  echo $! >"$RUN/api.pid"
  wait_http "http://127.0.0.1:${API_PORT}/health" || { echo "API did not come up, see final_test/logs/api.log"; exit 1; }
  if [ "$mode" = production ] && [ "${TUNNEL:-1}" = 1 ]; then
    pkill -f "ngrok http" 2>/dev/null || true; sleep 1
    local host; host="$(host_of "$(envval FINAL_TEST_TUNNEL_API_URL)")"
    [ -f "$HOME/ngrok.yml" ] || { echo "~/ngrok.yml missing (copy of the ngrok config)"; exit 1; }
    setsid nohup ngrok http "$PROXY_PORT" --url="https://${host}" --config "$HOME/ngrok.yml" >"$LOGS/ngrok.log" 2>&1 </dev/null &
    echo $! >"$RUN/ngrok.pid"
    wait_http "https://${host}/health" || { echo "tunnel did not come up, see final_test/logs/ngrok.log"; exit 1; }
  fi
  cmd_status "$mode"
}

cmd_down() {
  stop_api; pkill -f "ngrok http" 2>/dev/null || true; rm -f "$RUN/ngrok.pid"
  docker rm -f "$CADDY_NAME" >/dev/null 2>&1 || true
  [ "${1:-}" = "--all" ] && docker stop "$PG_NAME" >/dev/null 2>&1 || true
  echo "stopped"
}

cmd_status() {
  local mode="${1:-production}"
  printf "postgres  : "; docker exec "$PG_NAME" pg_isready -U builder -d builder 2>&1 | tail -1
  printf "api       : "; curl -s -o /dev/null -w "HTTP %{http_code}\n" "http://127.0.0.1:${API_PORT}/health" || echo down
  printf "proxy app : "; curl -s -o /dev/null -w "HTTP %{http_code}\n" "http://127.0.0.1:${PROXY_PORT}/" || echo down
  printf "proxy api : "; curl -s -o /dev/null -w "HTTP %{http_code}\n" "http://127.0.0.1:${PROXY_PORT}/health" || echo down
  local t; t="$(envval FINAL_TEST_TUNNEL_API_URL)"
  if [ -n "$t" ]; then printf "tunnel    : "; curl -s -o /dev/null -w "HTTP %{http_code}  ($(host_of "$t"))\n" -H 'ngrok-skip-browser-warning: 1' "$t/health" || echo down; fi
}

cmd_snapshot() { local n="${1:?name}"; docker exec "$PG_NAME" pg_dump -U builder -Fc "$DB_NAME" >"$SNAP/$n.dump"; chmod 600 "$SNAP/$n.dump"; echo "saved $SNAP/$n.dump ($(du -h "$SNAP/$n.dump" | cut -f1))"; }

cmd_restore() {
  local n="${1:?name}"; [ -f "$SNAP/$n.dump" ] || { echo "no snapshot $n (have: $(ls "$SNAP" | tr '\n' ' '))"; exit 1; }
  stop_api; ensure_pg
  docker exec "$PG_NAME" psql -U builder -d postgres -c "select pg_terminate_backend(pid) from pg_stat_activity where datname='${DB_NAME}'" >/dev/null
  docker exec "$PG_NAME" psql -U builder -d postgres -c "drop database if exists \"${DB_NAME}\"" -c "create database \"${DB_NAME}\"" >/dev/null
  docker exec -i "$PG_NAME" pg_restore -U builder -d "$DB_NAME" --no-owner <"$SNAP/$n.dump"
  echo "restored $n into $DB_NAME; now run: stack.sh up"
}

case "${1:-}" in
  up) cmd_up "${2:-production}";;
  down) cmd_down "${2:-}";;
  status) cmd_status;;
  snapshot) cmd_snapshot "${2:-}";;
  restore) cmd_restore "${2:-}";;
  logs) tail -n 60 "$LOGS/${2:-api}.log";;
  *) sed -n 2,14p "${BASH_SOURCE[0]}"; exit 1;;
esac
