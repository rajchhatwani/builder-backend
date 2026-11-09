#!/usr/bin/env bash
# Go-live checklist P1-P6 (read-only, no root needed). Prints PASS/FAIL per line; exit 1 on any FAIL.
# Uses the same BUILDER_* environment as the API. Prints no secret values.
cd "$(dirname "$0")/.."
fails=0
res() { # name status detail
  if [ "$2" = 0 ]; then echo "PASS  $1  $3"; else echo "FAIL  $1  $3"; fails=$((fails+1)); fi
}
py() { uv run python -c "$1" 2>&1; }

out=$(py "
import asyncio
from app.config import get_settings
from app.services.sandbox.factory import make_sandbox
s=get_settings()
assert s.sandbox_runner_url, 'BUILDER_SANDBOX_RUNNER_URL unset'
asyncio.run(make_sandbox(s).check_runtime())
print('runner reachable, runtime ok')") ; res "P1 runner reachable" $? "$(echo "$out" | tail -1)"

if docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q runsc; then rc=0; d="runsc registered"; else rc=1; d="runsc not registered with docker"; fi
res "P1 runtime registered" $rc "$d"

d=$(scripts/sandbox_firewall.sh status --yes 2>&1 | tail -1); echo "$d" | grep -q "hooked into" && rc=0 || rc=1
res "P2 firewall" $rc "$d"

out=$(uv run python -m app.core.rls check-role 2>&1 | tail -1); echo "$out" | grep -q "API role ok" && rc=0 || rc=1
res "P3/P5 RLS API role" $rc "$out"

out=$(py "
from app.config import get_settings
from app.core.production_checks import production_problems
p=production_problems(get_settings()); print('; '.join(p) if p else 'ok'); raise SystemExit(1 if p else 0)"); res "P4/P5 production settings" $? "$(echo "$out" | tail -1)"

out=$(py "
from app.config import get_settings
s=get_settings(); assert s.preview_scheduler_enabled, 'preview_scheduler_enabled is false'; assert s.preview_root, 'preview_root unset'
assert s.rls_enabled, 'rls_enabled is false'
print('scheduler on, preview_root set, rls on')"); res "P4 scheduler/preview_root/rls" $? "$(echo "$out" | tail -1)"

out=$(py "
from app.core import crypto
print('active key id', crypto.active_key_id())"); echo "$out" | grep -q "^active key id" && rc=0 || rc=1
res "P6 key provider" $rc "$(echo "$out" | tail -1)"
out=$(py "
from app.config import get_settings
s=get_settings()
w = bool(s.public_api_url) and not s.public_api_url.startswith(('http://localhost','http://127.')) and not s.trust_proxy_headers
print('WARN' if w else 'ok')"); if echo "$out" | tail -1 | grep -q WARN; then
  echo "WARN  P4 proxy headers  public_api_url is set but trust_proxy_headers=false: behind a reverse proxy all preview visitors share one rate bucket (set BUILDER_TRUST_PROXY_HEADERS=true if the proxy sets X-Forwarded-For)"; fi
echo "NOTE  P2 firewall matches the sandbox subnet pool (SANDBOX_SUBNET_POOL, default 172.30.0.0/16) by range: later preview networks need no reapply; re-run sandbox_hostile_check.sh after apply"
echo "--- $fails FAIL"
[ "$fails" = 0 ]
