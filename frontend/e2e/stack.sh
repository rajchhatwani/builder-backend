#!/usr/bin/env bash
# Throwaway stack for the Playwright suite: Postgres (docker, own port) + API + built frontend.
# Playwright starts this (`bash e2e/stack.sh run`) and stops it; nothing here touches your dev DB.
# Ports: postgres 55432, api 8765, web 5199. Override with E2E_PG_PORT / E2E_API_PORT / E2E_WEB_PORT.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PG_PORT="${E2E_PG_PORT:-55432}"; API_PORT="${E2E_API_PORT:-8765}"; WEB_PORT="${E2E_WEB_PORT:-5199}"
PG_NAME="bb-e2e-pg"
OWNER_URL="postgresql+asyncpg://builder:builder@127.0.0.1:${PG_PORT}/builder"
APP_URL="postgresql+asyncpg://builder_app:builder_app@127.0.0.1:${PG_PORT}/builder"
ORIGIN="http://localhost:${WEB_PORT}"
LOG="$HERE/.logs"; mkdir -p "$LOG"
pids=()

cleanup() { for p in "${pids[@]:-}"; do kill "$p" 2>/dev/null || true; done; docker rm -f "$PG_NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM

# Orphans from a previous run (Playwright may SIGKILL this script before the trap runs).
for port in "$API_PORT" "$WEB_PORT"; do
  pid="$(ss -ltnp 2>/dev/null | grep ":${port} " | sed -E 's/.*pid=([0-9]+).*/\1/' | head -1 || true)"
  [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
done

[ "${1:-run}" = run ] || { echo "usage: $0 run"; exit 2; }

docker rm -f "$PG_NAME" >/dev/null 2>&1 || true
docker run -d --name "$PG_NAME" -e POSTGRES_USER=builder -e POSTGRES_PASSWORD=builder -e POSTGRES_DB=builder \
  -p "127.0.0.1:${PG_PORT}:5432" -v "$ROOT/scripts/db/10-app-role.sql:/docker-entrypoint-initdb.d/10-app-role.sql:ro" \
  postgres:16-alpine >/dev/null
for _ in $(seq 1 60); do
  docker exec "$PG_NAME" psql -U builder -d builder -Atc "select 1 from pg_roles where rolname='builder_app'" 2>/dev/null | grep -q 1 && break
  sleep 1
done

export BUILDER_DATABASE_URL="$APP_URL" BUILDER_MIGRATIONS_DATABASE_URL="$OWNER_URL"
export SECRET_KEY="e2e-only-secret-key-not-for-anything-real" BUILDER_ENVIRONMENT=local
export BUILDER_CORS_ORIGINS="[\"${ORIGIN}\"]" BUILDER_PUBLIC_APP_URL="$ORIGIN" BUILDER_PUBLIC_API_URL="http://localhost:${API_PORT}"
export BUILDER_SIGNUP_MODE=open BUILDER_ADMIN_MFA_REQUIRED=false BUILDER_AUTH_RATE_LIMIT_ATTEMPTS=100000
export BUILDER_BOOTSTRAP_ADMIN_EMAIL="e2e-admin@example.com" BUILDER_BOOTSTRAP_ADMIN_PASSWORD="Quartz-Lantern-Velvet-47"

( cd "$ROOT" && uv run alembic upgrade head >"$LOG/alembic.log" 2>&1 )
( cd "$ROOT" && uv run uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" >"$LOG/api.log" 2>&1 ) & pids+=($!)
for _ in $(seq 1 90); do curl -fs -o /dev/null "http://127.0.0.1:${API_PORT}/health" && break; sleep 1; done
curl -fs -o /dev/null "http://127.0.0.1:${API_PORT}/health" || { echo "api did not start, see $LOG/api.log"; exit 1; }
( cd "$ROOT/frontend" && VITE_API_BASE_URL="http://localhost:${API_PORT}" npx vite build --outDir "$HERE/.dist" --emptyOutDir >"$LOG/build.log" 2>&1 )
( cd "$ROOT/frontend" && npx vite preview --outDir "$HERE/.dist" --host 127.0.0.1 --port "$WEB_PORT" --strictPort >"$LOG/web.log" 2>&1 ) & pids+=($!)
echo "e2e stack up: web $ORIGIN api http://localhost:${API_PORT}"
wait
