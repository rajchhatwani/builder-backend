#!/usr/bin/env bash
# Builds bb-preview-app:1 (P4) from docker/preview-app: runtime deps only, non-root uid 10001.
# Run on the runner host. The build needs network (pip); the sandbox then runs it with none.
set -euo pipefail
cd "$(dirname "$0")/.."
TAG=${1:-bb-preview-app:1}
docker build -t "$TAG" docker/preview-app
uid=$(docker run --rm --network none --entrypoint id "$TAG" -u)
[ "$uid" != "0" ] || { echo "image runs as root: refusing"; exit 1; }
echo "built $TAG (uid $uid)"
