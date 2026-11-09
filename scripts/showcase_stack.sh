#!/usr/bin/env bash
# Persistent local stack for the demo/showcase (NOT the Playwright stack): Postgres (docker volume)
# + API + built dashboard. Usage: scripts/showcase_stack.sh start|stop|status
# Ports: postgres 55434, api 8780, web 5180 (override with SC_PG_PORT / SC_API_PORT / SC_WEB_PORT).
# Env: SC_ADMIN_EMAIL/SC_ADMIN_PASSWORD (seed login), SC_PREVIEW_ORIGIN, SC_ALLOW_PUBLIC, SC_ADMIN_MFA.
# The model key comes from the git-ignored .env.local (BUILDER_AI_API_KEY); only orgs listed in
# BUILDER_AI_PLATFORM_KEY_ORGS may use it, and the platform hard cap bounds the spend.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$ROOT/scripts/model_budget.sh"  # S2-008: one console limit shared by every stack (.bb-model-budget)
PG_PORT="${SC_PG_PORT:-55434}"; API_PORT="${SC_API_PORT:-8780}"; WEB_PORT="${SC_WEB_PORT:-5180}"
SECRETS="$HOME/.local/share/builder-showcase"; mkdir -p "$SECRETS"; chmod 700 "$SECRETS"
PG_NAME="bb-showcase-pg"; DATA="$ROOT/.showcase-data"; mkdir -p "$DATA/ws" "$DATA/previews" "$DATA/logs"
OWNER_URL="postgresql+asyncpg://builder:builder@127.0.0.1:${PG_PORT}/builder"
APP_URL="postgresql+asyncpg://builder_app:builder_app@127.0.0.1:${PG_PORT}/builder"
PUBLIC_WEB="${SC_PUBLIC_WEB:-http://localhost:${WEB_PORT}}"; PUBLIC_API="${SC_PUBLIC_API:-http://localhost:${API_PORT}}"
# Open sign-up and no admin MFA are only safe on localhost: refuse a public URL unless explicitly allowed.
for u in "$PUBLIC_WEB" "$PUBLIC_API"; do
  # exact host match (a prefix match let http://localhost:x@evil.com and http://127.0.0.1.evil.com through)
  if ! printf "%s" "$u" | grep -Eq '^http://(localhost|127\.0\.0\.1)(:[0-9]+)?/?$'; then
    [ "${SC_ALLOW_PUBLIC:-0}" = 1 ] || { echo "refusing non-local $u (open sign-up, no admin MFA); set SC_ALLOW_PUBLIC=1 to override"; exit 2; }
  fi
done
# Workbench preview origin is OPT-IN: this stack has no proxy on :8799. Set SC_PREVIEW_ORIGIN (e.g. the Caddy
# origin of docker/manual/Caddyfile) to enable the Workbench; unset leaves it inert with an explanatory message.
PREVIEW_ORIGIN="${SC_PREVIEW_ORIGIN:-}"
# Admin MFA is off for the local demo only; SC_ADMIN_MFA=true keeps it on.
ADMIN_MFA_REQUIRED="${SC_ADMIN_MFA:-false}"

env_up() {
  export BUILDER_DATABASE_URL="$APP_URL" BUILDER_MIGRATIONS_DATABASE_URL="$OWNER_URL"
  export SECRET_KEY="${SC_SECRET_KEY:-$(cat "$SECRETS/secret_key" 2>/dev/null || (head -c 32 /dev/urandom | base64 | tr -d '/+=' | tee "$SECRETS/secret_key"))}"
  export BUILDER_ENVIRONMENT=local BUILDER_SIGNUP_MODE=open BUILDER_ADMIN_MFA_REQUIRED="$ADMIN_MFA_REQUIRED"
  export BUILDER_CORS_ORIGINS="[\"${PUBLIC_WEB}\",\"http://localhost:${WEB_PORT}\"]"
  export BUILDER_PUBLIC_APP_URL="$PUBLIC_WEB" BUILDER_PUBLIC_API_URL="$PUBLIC_API"
  export BUILDER_WORKSPACE_ROOT="$DATA/ws" BUILDER_WORKSPACE_DB_ADMIN_URL="$OWNER_URL"
  export BUILDER_PREVIEW_ROOT="$DATA/previews" BUILDER_PREVIEW_SCHEDULER_ENABLED=true
  # The model key works only for the showcase org, listed by ID (looked up here; [] until it exists).
  SC_ORG_ID="$(docker exec "$PG_NAME" psql -U builder -d builder -Atc "select id from organizations where slug='showcase'" 2>/dev/null || true)"
  export BUILDER_AI_PLATFORM_KEY_ORGS="${BUILDER_AI_PLATFORM_KEY_ORGS:-[${SC_ORG_ID:+\"$SC_ORG_ID\"}]}"
}

case "${1:-}" in
  start)
    docker start "$PG_NAME" >/dev/null 2>&1 || docker run -d --name "$PG_NAME" -e POSTGRES_USER=builder \
      -e POSTGRES_PASSWORD=builder -e POSTGRES_DB=builder -p "127.0.0.1:${PG_PORT}:5432" \
      -v bb-showcase-pgdata:/var/lib/postgresql/data \
      -v "$ROOT/scripts/db/10-app-role.sql:/docker-entrypoint-initdb.d/10-app-role.sql:ro" postgres:16-alpine >/dev/null
    for _ in $(seq 1 60); do docker exec "$PG_NAME" pg_isready -U builder -d builder >/dev/null 2>&1 && break; sleep 1; done
    env_up; cd "$ROOT"
    uv run alembic upgrade head >"$DATA/logs/alembic.log" 2>&1
    nohup uv run uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" >"$DATA/logs/api.log" 2>&1 & echo $! >"$DATA/api.pid"
    for _ in $(seq 1 90); do curl -fs -o /dev/null "http://127.0.0.1:${API_PORT}/health" && break; sleep 1; done
    # S2-008: this database's spend cap is carved out of the shared console limit (SC_AI_CAP, default 1 USD)
    CAP0="$(budget_alloc showcase "${SC_AI_CAP:-1000000}")"
    docker exec "$PG_NAME" psql -U builder -d builder -Atq -c "insert into ai_platform_budget(id,cap_override_micro_usd) values(1,$CAP0) on conflict (id) do update set cap_override_micro_usd=$CAP0" >/dev/null
    curl -fs -o /dev/null "http://127.0.0.1:${API_PORT}/health" || { echo "api did not start: $DATA/logs/api.log"; exit 1; }
    ( cd frontend && VITE_API_BASE_URL="$PUBLIC_API" VITE_PREVIEW_API_ORIGIN="$PREVIEW_ORIGIN" npx vite build --outDir "$DATA/dist" --emptyOutDir >"$DATA/logs/build.log" 2>&1 )
    ( cd frontend && nohup npx vite preview --outDir "$DATA/dist" --host 127.0.0.1 --port "$WEB_PORT" --strictPort >"$DATA/logs/web.log" 2>&1 & echo $! >"$DATA/web.pid" )
    echo "showcase stack up: web http://localhost:${WEB_PORT}  api http://localhost:${API_PORT}" ;;
  stop)
    for f in api web; do [ -f "$DATA/$f.pid" ] && kill "$(cat "$DATA/$f.pid")" 2>/dev/null || true; rm -f "$DATA/$f.pid"; done
    for port in "$API_PORT" "$WEB_PORT"; do pid="$(ss -ltnp 2>/dev/null | grep ":${port} " | sed -E 's/.*pid=([0-9]+).*/\1/' | head -1 || true)"; [ -n "$pid" ] && kill "$pid" 2>/dev/null || true; done
    docker stop "$PG_NAME" >/dev/null 2>&1 || true; echo stopped ;;
  status) curl -fs "http://127.0.0.1:${API_PORT}/health" >/dev/null && echo "api up" || echo "api down"; docker ps --filter name="$PG_NAME" --format '{{.Names}} {{.Status}}' ;;
  *) echo "usage: $0 start|stop|status"; exit 2 ;;
esac
