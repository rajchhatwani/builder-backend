#!/usr/bin/env bash
# Manual-test stack (compose project bbmanual). Config comes ONLY from ~/final_test.env at run time (never printed,
# never written to a file except the 600-mode Stripe CLI secret, deleted on `down`). See studio/10-manual-test/00-START-HERE.md
#   up [local|public]   build + start everything (BB_MAIL=sink or MAIL=sink sends app mail to Mailpit instead of real SMTP)
#   down                stop everything (data kept)       reset   delete DB + volumes + data, then stopped
#   status | matrix | okta | logs [svc|stripe|ngrok]
#   seed                standard test accounts            enable-ai <org-slug>      set-ai-cap <micro_usd>
#   stripe [start|stop] Stripe CLI forwarder              stripe-trigger <event>  (checkout.session.completed needs a business name set in the Stripe dashboard)    tunnel [start|stop]  ngrok
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="$HOME/.local/share/bbmanual"; DATA="$STATE/data"; LOGS="$STATE/logs"
HELP="python3 $ROOT/scripts/manual_helper.py"
COMPOSE=(docker compose -f "$ROOT/docker-compose.manual.yml")
ENV_FILE="${ENV_FILE:-$HOME/final_test.env}"; export ENV_FILE
PORTS="8000 8081 8799 5432 6379 9000 1025 8025"

dc() { $HELP run -- "${COMPOSE[@]}" "$@"; }
psql_() { docker exec -i bbmanual-postgres psql -U builder -d builder -Atq "$@"; }
prep() { [ -f "$ENV_FILE" ] || { echo "env file $ENV_FILE not found"; exit 1; }
  umask 077; mkdir -p "$STATE" "$LOGS"; chmod 700 "$STATE"; umask 022; mkdir -p "$DATA/ws" "$DATA/previews"; }
mode() { cat "$STATE/mode" 2>/dev/null || echo local; }
pid_alive() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }
stop_bg() { if pid_alive "$1"; then kill "$(cat "$1")" 2>/dev/null || true; fi; rm -f "$1"; }

check_ports() {
  docker inspect -f '{{.State.Running}}' bbmanual-postgres 2>/dev/null | grep -q true && return 0  # our own stack
  local bad=0
  for p in $PORTS; do
    if ss -ltn "sport = :$p" 2>/dev/null | grep -q LISTEN; then
      local who; who="$(docker ps --format '{{.Names}} {{.Ports}}' | grep -E ":$p->" | awk '{print $1}' | head -1)"
      echo "PORT $p is already in use ${who:+by container $who}${who:-(another process)}."; bad=1
    fi
  done
  if [ $bad = 1 ]; then echo "Stop the holder first (old harness: final_test/harness/stack.sh down --all). This script does not touch containers it did not create."; exit 1; fi
}

stage_ctx() {  # small build contexts (the classic builder would send node_modules, tests, .git ...)
  local c="$STATE/ctx"; rm -rf "${c:?}"; mkdir -p "$c/api" "$c/web/docker/manual"
  ( cd "$ROOT" && cp -a pyproject.toml uv.lock alembic.ini app alembic scripts "$c/api/" && cp docker/manual/Dockerfile.api "$c/api/Dockerfile" )
  find "$c/api" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
  ( cd "$ROOT" && tar -c --exclude=node_modules --exclude=dist --exclude=e2e --exclude=test-results --exclude=playwright-report frontend | tar -x -C "$c/web" \
    && cp docker/manual/Caddyfile "$c/web/docker/manual/Caddyfile" && cp docker/manual/Dockerfile.web "$c/web/Dockerfile" )
}

wait_api() { local n=0; until curl -fs -o /dev/null http://127.0.0.1:8000/health; do n=$((n+1)); [ $n -gt 120 ] && { echo "API did not become healthy: scripts/manual_stack.sh logs api"; exit 1; }; sleep 2; done; }

restart_api() { dc up -d --no-deps --force-recreate api >/dev/null 2>&1; wait_api; }

cmd_up() {
  local m="${1:-local}"; case "$m" in local|public) ;; *) echo "usage: up [local|public]"; exit 1;; esac
  prep; check_ports
  echo "$m" >"$STATE/mode"; MAILMODE=real; [ "${BB_MAIL:-${MAIL:-}}" = sink ] && MAILMODE=sink; echo "$MAILMODE" >"$STATE/mail"
  if [ "$m" = public ] && [ -z "$($HELP get FINAL_TEST_TUNNEL_API_URL)" ]; then echo "FINAL_TEST_TUNNEL_API_URL missing in env"; exit 1; fi
  docker image inspect bb-preview-app:1 >/dev/null 2>&1 || echo "WARNING: image bb-preview-app:1 missing: previews will fail (build docker/preview-app)"
  echo "!!! WARNING: the API container mounts /var/run/docker.sock = root on this host. LOCAL TESTING ONLY (the unsafe setup backlog P1 is about)."
  echo "building + starting (mode=$m, mail=$MAILMODE) ..."
  stage_ctx
  dc up -d --build >"$LOGS/up.log" 2>&1 || { tail -30 "$LOGS/up.log"; echo "compose up failed (full log: $LOGS/up.log)"; exit 1; }
  wait_api
  # platform AI budget: only on a fresh counter (never overwrites a cap the owner raised)
  psql_ -c "insert into ai_platform_budget(id,spent_micro_usd,cap_override_micro_usd) values(1,1677831,2680000) on conflict (id) do update set spent_micro_usd=1677831, cap_override_micro_usd=2680000 where ai_platform_budget.spent_micro_usd=0 and ai_platform_budget.cap_override_micro_usd is null" >/dev/null
  # MinIO bucket from STORAGE_* (created from inside the API container, which has the env)
  docker exec -i bbmanual-api python - <<'PY' || echo "WARNING: MinIO bucket creation failed (see troubleshooting: MinIO bucket)"
import os, time, boto3
from botocore.config import Config
c = boto3.client("s3", endpoint_url=os.environ["STORAGE_ENDPOINT_URL"], region_name=os.environ.get("STORAGE_REGION", "us-east-1"),
    aws_access_key_id=os.environ["STORAGE_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["STORAGE_SECRET_ACCESS_KEY"], config=Config(retries={"max_attempts": 1}))
b = os.environ["STORAGE_BUCKET"]
from botocore.exceptions import ClientError
ok = False
for _ in range(60):
    try:
        c.head_bucket(Bucket=b); ok = True; break
    except ClientError as e:
        if str(e.response.get("Error", {}).get("Code", "")) in ("404", "NoSuchBucket"):
            try:
                c.create_bucket(Bucket=b); ok = True; break
            except Exception:
                pass
    except Exception:
        pass
    time.sleep(1)
if not ok:
    raise SystemExit("bucket not ready")
print("bucket ready")
PY
  if [ "$m" = public ]; then cmd_tunnel start; fi
  cmd_status
}

cmd_status() {
  echo "--- containers"; docker ps -a --filter name=bbmanual- --format '  {{.Names}}  {{.Status}}'
  local o; o="$($HELP get BB_ORIGIN)"
  printf "  api        : "; curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8000/health || true
  printf "  dashboard  : "; curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8081/ || true
  printf "  proxy->api : "; curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8081/health || true
  printf "  preview org: "; curl -s -o /dev/null -w "HTTP %{http_code} (4xx = proxy up)\n" http://127.0.0.1:8799/previews/x/openapi.json || true
  echo "--- mode=$(mode)  open: $o   (also mailpit http://127.0.0.1:8025, api docs http://127.0.0.1:8000/docs)"
  if pid_alive "$STATE/ngrok.pid"; then echo "  ngrok running"; fi
  if pid_alive "$STATE/stripe.pid"; then echo "  stripe forwarder running"; fi
}

cmd_down() {
  stop_bg "$STATE/stripe.pid"; stop_bg "$STATE/ngrok.pid"; rm -f "${STATE:?}/stripe_whsec"
  dc down --remove-orphans >/dev/null 2>&1 || true
  echo "stopped (volumes and data kept; Stripe session secret deleted)."
}

cmd_reset() {
  echo "RESET: deleting"
  stop_bg "$STATE/stripe.pid"; stop_bg "$STATE/ngrok.pid"
  local ids nets
  ids="$(docker ps -aq --filter label=bb.sandbox=1 2>/dev/null || true)"; nets=""
  for c in $ids; do
    if docker inspect -f '{{range .Mounts}}{{.Source}} {{end}}' "$c" | grep -q "$DATA"; then
      nets="$nets $(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$c")"; fi
  done
  for n in $(echo $nets | tr ' ' '\n' | sort -u); do
    for c in $(docker ps -aq --filter network="$n"); do docker rm -f -v "$c" >/dev/null && echo "  sandbox container $c"; done
    if docker network rm "$n" >/dev/null 2>&1; then echo "  sandbox network $n"; fi
  done
  dc down -v --remove-orphans 2>&1 | sed 's/^/  /' || true
  echo "  volumes bbmanual_pgdata, bbmanual_miniodata (database, object store)"
  if [ -d "$DATA" ]; then
    docker run --rm -v "$DATA:/d" alpine sh -c 'rm -rf /d/* /d/.[!.]* 2>/dev/null; true' >/dev/null 2>&1 || true
    rmdir "$DATA" 2>/dev/null || true; echo "  data dir $DATA (previews, workspaces)"
  fi
  local f; for f in stripe_whsec ai_orgs.json mode mail ngrok.pid stripe.pid; do rm -f "${STATE:?}/$f"; done
  echo "  session state (mode, mail, AI org list, Stripe secret)"
  echo "reset done; stack is stopped. Start fresh: scripts/manual_stack.sh up local"
}

cmd_enable_ai() {
  local slug="${1:?usage: enable-ai <org-slug>}"
  [ -n "$($HELP run -- sh -c 'echo ${BUILDER_AI_API_KEY:+x}')" ] || { echo "No BUILDER_AI_API_KEY in $ROOT/.env.local: AI stays NOT CONNECTED."; exit 1; }
  local id; id="$(psql_ -c "select id from organizations where slug='${slug//\'/}'")"
  [ -n "$id" ] || { echo "no org with slug '$slug' (create it in the dashboard first)"; exit 1; }
  python3 - "$STATE/ai_orgs.json" "$id" <<'PY'
import json, sys, os
p, i = sys.argv[1:3]
cur = json.load(open(p)) if os.path.exists(p) else []
if i not in cur: cur.append(i)
open(p, "w").write(json.dumps(cur))
PY
  restart_api; echo "AI enabled for org $slug ($id). Platform cap: scripts/manual_stack.sh set-ai-cap <micro_usd>; check GET /orgs/$slug/ai/platform-budget"
}

cmd_set_ai_cap() {
  local n="${1:?usage: set-ai-cap <micro_usd>  (e.g. 4500000 = 4.50 USD)}"; [[ "$n" =~ ^[0-9]+$ ]] || { echo "number required"; exit 1; }
  psql_ -c "insert into ai_platform_budget(id,cap_override_micro_usd) values(1,$n) on conflict (id) do update set cap_override_micro_usd=$n"
  echo "cap override = $n micro-USD. Note: the effective cap is min(this, config cap 4,500,000)."
}

cmd_stripe() {
  case "${1:-start}" in
    stop) stop_bg "$STATE/stripe.pid"; rm -f "${STATE:?}/stripe_whsec"; echo "forwarder stopped; restart the API to drop the session secret (down/up)"; return;;
    start) ;; *) echo "usage: stripe [start|stop]"; exit 1;;
  esac
  local S="$HOME/.stripe/bin/stripe"; [ -x "$S" ] || { echo "Stripe CLI not found at $S"; exit 1; }
  curl -fs -o /dev/null http://127.0.0.1:8000/health || { echo "stack is not up"; exit 1; }
  if pid_alive "$STATE/stripe.pid"; then echo "forwarder already running"; return; fi
  local sec; sec="$($HELP run -- "$S" listen --print-secret 2>/dev/null | tail -1)" || true
  if [[ "$sec" != whsec_* ]]; then
    echo "Stripe CLI could not authenticate. Log in once (opens a browser): $S login   (the env key is also tried via STRIPE_API_KEY)"; exit 1; fi
  ( umask 077; printf '%s' "$sec" >"$STATE/stripe_whsec" ); sec=""
  $HELP run -- setsid nohup bash -c 'echo $$ >"'"$STATE"'/stripe.pid"; exec "'"$S"'" listen --events checkout.session.completed,customer.subscription.created,customer.subscription.updated,customer.subscription.deleted,invoice.payment_failed --forward-to http://127.0.0.1:8000/billing/stripe/webhook > >(sed -u -E "s/(whsec_|sk_test_|rk_test_)[A-Za-z0-9]+/\1[REDACTED]/g" >"'"$LOGS"'/stripe.log") 2>&1' </dev/null >/dev/null 2>&1 &
  sleep 3; restart_api
  if pid_alive "$STATE/stripe.pid"; then echo "Stripe forwarder running (log: $LOGS/stripe.log). Test: scripts/manual_stack.sh stripe-trigger customer.subscription.created"; else echo "forwarder failed: see $LOGS/stripe.log"; exit 1; fi
}

cmd_stripe_trigger() { $HELP run -- "$HOME/.stripe/bin/stripe" trigger "${1:-checkout.session.completed}" 2>&1 | sed -E 's/(whsec_|sk_test_|rk_test_)[A-Za-z0-9]+/\1[REDACTED]/g' | tail -8; }

cmd_tunnel() {
  case "${1:-start}" in
    stop) stop_bg "$STATE/ngrok.pid"; echo "tunnel stopped"; return;;
    start) ;; *) echo "usage: tunnel [start|stop]"; exit 1;;
  esac
  if pid_alive "$STATE/ngrok.pid"; then echo "tunnel already running"; return; fi
  if pgrep -x ngrok >/dev/null 2>&1; then echo "another ngrok process is running (old harness?). Stop it first: final_test/harness/stack.sh down"; exit 1; fi
  [ -f "$HOME/ngrok.yml" ] || { echo "~/ngrok.yml missing (ngrok config with the authtoken)"; exit 1; }
  [ "$(mode)" = public ] || echo "note: stack is in local mode; the dashboard/API URLs are localhost. Use: up public"
  local url host; url="$($HELP get FINAL_TEST_TUNNEL_API_URL)"; host="${url#https://}"; host="${host%%/*}"
  prep
  setsid nohup bash -c 'echo $$ >"'"$STATE"'/ngrok.pid"; exec ngrok http 8081 --url="https://'"$host"'" --config "$HOME/ngrok.yml"' >"$LOGS/ngrok.log" 2>&1 </dev/null &
  local n=0; until curl -fs -o /dev/null -H 'ngrok-skip-browser-warning: 1' "https://$host/health"; do n=$((n+1)); if [ $n -gt 30 ]; then echo "tunnel did not come up: $LOGS/ngrok.log (check ~/ngrok.yml / authtoken / domain)"; exit 1; fi; sleep 1; done
  echo "tunnel up: https://$host (use header ngrok-skip-browser-warning: 1 for curl)"
}

case "${1:-}" in
  up) cmd_up "${2:-local}";;
  down) cmd_down;;
  reset) prep; cmd_reset;;
  status) cmd_status;;
  matrix) $HELP matrix;;
  okta) $HELP okta;;
  logs) s="${2:-api}"; case "$s" in stripe|ngrok) tail -n 80 "$LOGS/$s.log";; *) dc logs --tail 100 "$s" 2>&1 | grep -v '^$';; esac;;
  seed) $HELP seed;;
  enable-ai) cmd_enable_ai "${2:-}";;
  set-ai-cap) cmd_set_ai_cap "${2:-}";;
  stripe) cmd_stripe "${2:-start}";;
  stripe-trigger) cmd_stripe_trigger "${2:-}";;
  tunnel) cmd_tunnel "${2:-start}";;
  *) sed -n 2,9p "${BASH_SOURCE[0]}"; exit 1;;
esac
