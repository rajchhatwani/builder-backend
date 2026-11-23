#!/usr/bin/env bash
# Impact test: run ONLY the checks the current (uncommitted) change can break. Never commits, never edits files.
#
#   scripts/impact_test.sh [--plan] [--staged] [--base REF] [--depth N] [--hubs unit|skip]
#                          [--e2e] [--slow] [--no-mypy] [--strict]
#
#   (default)  working tree vs HEAD, including untracked files
#   --plan     print the blast radius and the exact work lists, run nothing
#   --staged   only what is staged (use right before `git commit`)
#   --base REF compare against REF instead of HEAD (e.g. the checkpoint start commit)
#   --depth N  reverse-import hops counted as blast radius (default 1)
#   --hubs     a hub module (imported by >25 app modules) changed: "unit" runs the whole unit suite
#              (no Docker, ~11 min), "skip" only warns
#   --e2e      also run the Playwright specs that mention the changed frontend files
#   --slow     also run selected tests/e2e (generated-project, Docker, slow)
#   --strict   exit 3 if a changed app file is reached by no test at all
#
# Output: one "IMPACT <step>: PASS|FAIL ..." line per step, then "IMPACT RESULT: GREEN|RED".
# Logs and work lists: studio/13-mcp/impact-runs/<timestamp>/  (override with IMPACT_OUT=dir)
set -u
cd "$(dirname "$0")/.."

plan=0; staged=0; base=""; depth=1; hubs=unit; e2e=0; slow=0; mypy=1; strict=0
while [ $# -gt 0 ]; do
  case "$1" in
    --plan) plan=1;; --staged) staged=1;; --e2e) e2e=1;; --slow) slow=1;; --no-mypy) mypy=0;; --strict) strict=1;;
    --base) base="${2:?--base needs a ref}"; shift;;
    --depth) depth="${2:?--depth needs a number}"; shift;;
    --hubs) hubs="${2:?--hubs needs unit|skip}"; shift;;
    -h|--help) sed -n '2,20p' "$0"; exit 0;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2;;
  esac; shift
done

OUT="${IMPACT_OUT:-studio/13-mcp/impact-runs}/$(date +%m%d-%H%M%S)"
mkdir -p "$OUT"
margs=(--out "$OUT" --depth "$depth" --hubs "$hubs")
[ -n "$base" ] && margs+=(--base "$base")
[ "$staged" -eq 1 ] && margs+=(--staged)
python3 -I scripts/impact_map.py "${margs[@]}" || { echo "IMPACT RESULT: RED (mapper failed)"; exit 2; }
echo "work lists + logs: $OUT"
[ "$plan" -eq 1 ] && exit 0

fail=0
step() { # name, logfile-name, command...
  local name="$1" lf="$OUT/$2.log"; shift 2
  local t0=$SECONDS
  "$@" >"$lf" 2>&1; local rc=$?
  local last; last="$(grep -E 'passed|failed|error|Found|All checks|Success|Tests ' "$lf" | tail -1)"
  if [ $rc -eq 0 ]; then echo "IMPACT $name: PASS ${last} ($((SECONDS - t0))s)"
  else echo "IMPACT $name: FAIL ${last:-rc=$rc} ($((SECONDS - t0))s)  -> $lf"; fail=1; fi
}
nonempty() { [ -s "$OUT/$1" ]; }
docker_ok() { docker info >/dev/null 2>&1; }

# ---- python: cheapest first so a typo fails in seconds, not after the Docker suite ----
if nonempty ruff.txt; then mapfile -t f < "$OUT/ruff.txt"; step ruff ruff uv run ruff check "${f[@]}" --select E,W,F --ignore E501; fi
if [ "$mypy" -eq 1 ] && nonempty mypy.flag; then step mypy mypy uv run mypy app; fi
if nonempty unit.txt; then mapfile -t f < "$OUT/unit.txt"; step "unit(${#f[@]} files)" unit uv run pytest "${f[@]}" -q -p no:cacheprovider; fi
if nonempty api.txt; then
  mapfile -t f < "$OUT/api.txt"
  if docker_ok; then step "api(${#f[@]} files)" api uv run pytest "${f[@]}" -q -p no:cacheprovider
  else echo "IMPACT api(${#f[@]} files): FAIL docker unavailable (start Docker, then rerun)"; fail=1; fi
fi
if [ "$slow" -eq 1 ] && nonempty slow.txt; then
  mapfile -t f < "$OUT/slow.txt"
  if docker_ok; then step "slow-e2e(${#f[@]} files)" slow uv run pytest "${f[@]}" -q -p no:cacheprovider
  else echo "IMPACT slow-e2e: FAIL docker unavailable"; fail=1; fi
elif nonempty slow.txt; then echo "IMPACT slow-e2e: NOT RUN ($(wc -l < "$OUT/slow.txt") file(s) selected; add --slow)"; fi

# ---- frontend ----
if nonempty tsc.flag; then step tsc tsc npm --prefix frontend exec -- tsc --noEmit; fi
if nonempty vitest.txt; then
  mapfile -t f < "$OUT/vitest.txt"
  step "vitest-related(${#f[@]})" vitest bash -c 'cd frontend && npx vitest related --run "$@"' _ "${f[@]}"
fi
if nonempty specs.txt; then
  mapfile -t f < "$OUT/specs.txt"
  if [ "$e2e" -eq 1 ]; then step "playwright(${#f[@]} specs)" playwright npm --prefix frontend run e2e --silent -- "${f[@]}"
  else echo "IMPACT playwright: NOT RUN (${#f[@]} spec(s) relevant: $(tr '\n' ' ' < "$OUT/specs.txt"); add --e2e)"; fi
fi

if [ "$strict" -eq 1 ] && grep -q '^NO TEST REACHES' "$OUT/report.txt"; then echo "IMPACT strict: FAIL changed code with no covering test"; fail=3; fi
if [ "$fail" -eq 0 ]; then echo "IMPACT RESULT: GREEN"; else echo "IMPACT RESULT: RED"; fi
echo "reminder: this is the affected slice only. The full gate (scripts/gate.sh after) is NOT run."
exit $fail
