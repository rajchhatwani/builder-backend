#!/usr/bin/env bash
# Regression gate. Usage: scripts/gate.sh before|after|quick
#  quick  = ruff + mypy + unit (no Docker)      before/after = quick + api (Docker) + frontend suites if present
# Output: one "GATE <name>: PASS|FAIL <detail>" line per suite, then "GATE RESULT: GREEN|RED".
set -u
cd "$(dirname "$0")/.."
mode="${1:-quick}"
case "$mode" in before|after|quick) ;; *) echo "usage: $0 before|after|quick" >&2; exit 2;; esac
fail=0
run() { # name, command...
  local name="$1"; shift
  local out; out="$("$@" 2>&1)"; local rc=$?
  local last; last="$(printf '%s\n' "$out" | grep -E 'passed|failed|error|Found|All checks|Success' | tail -1)"
  if [ $rc -eq 0 ]; then echo "GATE $name: PASS ${last}"; else echo "GATE $name: FAIL ${last:-rc=$rc}"; fail=1; fi
}
run ruff uv run ruff check app --select E,W,F --ignore E501
run mypy uv run mypy app
run unit uv run pytest tests/unit -q -p no:cacheprovider
if [ "$mode" != quick ]; then
  if docker info >/dev/null 2>&1; then run api uv run pytest tests/api -q -p no:cacheprovider
  else echo "GATE api: FAIL docker unavailable"; fail=1; fi
  if [ -s tests/regression_manifest.txt ]; then
    mapfile -t paths < <(grep -vE '^\s*(#|$)' tests/regression_manifest.txt)
    run manifest uv run pytest "${paths[@]}" -q -p no:cacheprovider
  fi
  if [ -f frontend/package.json ] && grep -q '"test"' frontend/package.json; then
    run frontend-unit npm --prefix frontend run test --silent
  else echo "GATE frontend-unit: SKIP no suite yet"; fi
  if [ -f frontend/playwright.config.ts ]; then run e2e npm --prefix frontend run e2e --silent
  else echo "GATE e2e: SKIP no suite yet"; fi
fi
if [ $fail -eq 0 ]; then echo "GATE RESULT: GREEN"; else echo "GATE RESULT: RED"; fi
exit $fail
