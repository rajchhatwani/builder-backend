#!/usr/bin/env bash
# Run on the server by the deploy workflow (or by hand): ./deploy.sh <image-tag>
# Order: pull -> database up -> migrate as owner -> (re)create the API role -> start everything -> health check.
set -euo pipefail
cd "$(dirname "$0")"
TAG="${1:?usage: deploy.sh <image-tag>}"
: "${BB_IMAGE_PREFIX:?BB_IMAGE_PREFIX must be exported (the workflow sets it)}"
[ -f .env ] || { echo ".env missing: copy .env.example and fill it in" >&2; exit 1; }
[ -f keys.txt ] || { echo "keys.txt missing: printf 'k1 %s\n' \"\$(openssl rand -base64 32)\" > keys.txt && chmod 600 keys.txt" >&2; exit 1; }
export BB_TAG="$TAG"
envval() { grep -E "^$1=" .env | tail -1 | cut -d= -f2-; }
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

previous="$(cat .current-tag 2>/dev/null || echo none)"
dc pull
if [ "$SANDBOX" = "true" ]; then
  # the sandbox never pulls images itself: put the preview image where it expects it
  docker pull "${BB_IMAGE_PREFIX}/builder-preview-app:${TAG}"
  docker tag "${BB_IMAGE_PREFIX}/builder-preview-app:${TAG}" bb-preview-app:1
fi
dc up -d --wait postgres keycloak-db
dc --profile tools run --rm migrate
dc --profile tools run --rm db-role
# row-level security ON for every org table (idempotent); the API refuses to start in production without it
dc --profile tools run --rm db-role /app/.venv/bin/python -m app.core.rls enable --yes
dc up -d --remove-orphans --wait
echo "$TAG" > .current-tag
echo "$previous" > .previous-tag

domain="$(grep -E '^BB_DOMAIN=' .env | cut -d= -f2-)"
for i in $(seq 1 30); do
  if curl -fsS "https://${domain}/health" >/dev/null; then echo "healthy: ${domain} on ${TAG}"; docker image prune -f >/dev/null; exit 0; fi
  sleep 5
done
echo "health check failed. Roll back with: ./deploy.sh ${previous}" >&2
exit 1
