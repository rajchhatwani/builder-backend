#!/usr/bin/env bash
# Shared model-spend budget (S2-008). ONE console key has ONE limit, but every local stack
# (manual, showcase, ...) has its own database and therefore its own ai_platform_budget row.
# This file (git-ignored, $ROOT/.bb-model-budget) is the single place that records
#   limit <micro_usd>          the console limit of the key (default 5000000 = 5 USD, set once)
#   <stack> <micro_usd>        what each stack's cap_override was granted
# budget_alloc keeps SUM(grants) <= limit, so the caps of all databases together can never exceed
# the one console limit. Source this file; do not run it.
BUDGET_FILE="${BB_MODEL_BUDGET_FILE:-${ROOT:-.}/.bb-model-budget}"

budget_limit() {
  [ -f "$BUDGET_FILE" ] || { echo "limit ${BB_MODEL_LIMIT_MICRO_USD:-5000000}" >"$BUDGET_FILE"; chmod 600 "$BUDGET_FILE"; }
  awk '$1=="limit"{print $2}' "$BUDGET_FILE" | head -1
}

# budget_alloc <stack> <wanted_micro_usd>  -> prints the granted cap (<= wanted, <= what is left)
budget_alloc() {
  local stack="$1" wanted="$2" limit others granted
  [[ "$wanted" =~ ^[0-9]+$ ]] || { echo "number required" >&2; return 1; }
  limit="$(budget_limit)"
  others="$(awk -v s="$stack" '$1!="limit" && $1!=s{n+=$2} END{print n+0}' "$BUDGET_FILE")"
  granted=$(( limit - others )); [ "$granted" -lt 0 ] && granted=0
  [ "$wanted" -lt "$granted" ] && granted="$wanted"
  { grep -v -e "^$stack " "$BUDGET_FILE" || true; echo "$stack $granted"; } >"$BUDGET_FILE.tmp" && mv "$BUDGET_FILE.tmp" "$BUDGET_FILE"
  [ "$granted" -lt "$wanted" ] && echo "model budget: $stack asked $wanted, granted $granted (limit $limit shared with other stacks)" >&2
  echo "$granted"
}
