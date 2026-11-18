#!/usr/bin/env bash
# Run on the server by the deploy workflow (or by hand): ./deploy.sh <image-tag>
# Roll back: ./deploy.sh --no-migrate <previous-tag> (skips the migration step; the old image cannot see newer revisions).
# Order: pull -> database up -> migrate as owner -> (re)create the API role -> start everything -> health check.
set -euo pipefail
cd "$(dirname "$0")"
MIGRATE=1
if [ "${1:-}" = "--no-migrate" ]; then MIGRATE=0; shift; fi
TAG="${1:?usage: deploy.sh [--no-migrate] <image-tag>}"
[ -f .env ] || { echo ".env missing: copy .env.example and fill it in" >&2; exit 1; }
# missing key -> empty (no silent exit under pipefail); strips CR and one pair of surrounding quotes
envval() { { grep -E "^$1=" .env || true; } | tail -1 | cut -d= -f2- | tr -d '\r' | sed -E "s/^(['\"])(.*)\1\$/\2/"; }
BB_IMAGE_PREFIX="${BB_IMAGE_PREFIX:-$(envval BB_IMAGE_PREFIX)}"
: "${BB_IMAGE_PREFIX:?BB_IMAGE_PREFIX must be exported or set in .env}"
export BB_IMAGE_PREFIX
[ -f keys.txt ] || { echo "keys.txt missing: printf 'k1 %s\n' \"\$(openssl rand -base64 32)\" > keys.txt && sudo chown 10001 keys.txt && sudo chmod 400 keys.txt (see docs/DEPLOY.md)" >&2; exit 1; }
export BB_TAG="$TAG"
FILES=(-f docker-compose.yml)
SANDBOX="$(envval SANDBOX_ENABLED)"
if [ "$SANDBOX" = "true" ]; then
  FILES+=(-f docker-compose.sandbox.yml)
  BB_DATA="$(envval BB_DATA)"; BB_DATA="${BB_DATA:-/var/lib/builder}"; export BB_DATA
  rt="$(envval BB_SANDBOX_RUNTIME)"; rt="${rt:-runsc}"
  docker info --format '{{json .Runtimes}}' | grep -q "\"$rt\"" \
    || { echo "sandbox: runtime '$rt' is not registered with Docker (install gVisor): see docs/DEPLOY.md" >&2; exit 1; }
  mkdir -p "$BB_DATA/previews" "$BB_DATA/ws"
fi
dc() { docker compose --env-file .env "${FILES[@]}" "$@"; }

current="$(cat .current-tag 2>/dev/null || echo none)"
if [ "$current" != "$TAG" ]; then previous="$current"; else previous="$(cat .previous-tag 2>/dev/null || echo none)"; fi
dc pull
if [ "$SANDBOX" = "true" ]; then
  # the sandbox never pulls images itself: put the preview image where it expects it
  docker pull "${BB_IMAGE_PREFIX}/builder-preview-app:${TAG}"
  docker tag "${BB_IMAGE_PREFIX}/builder-preview-app:${TAG}" bb-preview-app:1
fi
dc up -d --wait postgres keycloak-db
if [ "$MIGRATE" = "1" ]; then dc --profile tools run --rm migrate; else echo "rollback: migrations skipped"; fi
dc --profile tools run --rm db-role
# row-level security ON for every org table (idempotent); the API refuses to start in production without it
dc --profile tools run --rm db-role /app/.venv/bin/python -m app.core.rls enable --yes
dc up -d --remove-orphans --wait
echo "$previous" > .previous-tag
# drop superseded sha-tagged images of this project (keep this tag and the rollback target)
docker image ls --format '{{.Repository}}:{{.Tag}}' | grep -F "${BB_IMAGE_PREFIX}/builder-" | grep -E ':sha-' \
  | while read -r ref; do
      case "${ref##*:}" in "$TAG"|"$previous") ;; *) docker image rm "$ref" >/dev/null 2>&1 || true ;; esac
    done || true

domain="$(envval BB_DOMAIN)"
for i in $(seq 1 30); do
  if curl -fsS --connect-timeout 5 --max-time 10 "https://${domain}/health" >/dev/null; then
    echo "$TAG" > .current-tag
    echo "healthy: ${domain} on ${TAG}"; docker image prune -f >/dev/null; exit 0
  fi
  sleep 5
done
echo "health check failed. Roll back with: ./deploy.sh --no-migrate ${previous}" >&2
exit 1
