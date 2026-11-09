#!/usr/bin/env bash
# Hostile-container check for sandbox isolation (backlog P2). Needs docker and the configured runtime.
#
# Usage: scripts/sandbox_hostile_check.sh   (env: SANDBOX_RUNTIME=runsc IMAGE=python:3.12-slim)
#
# Runs a throwaway container on a bb.sandbox-labelled --internal network (exactly as the platform does,
# read-only, cap-drop ALL, non-root) plus a second "victim" sandbox, and tries to connect to:
#   gateway of its own network, cloud metadata 169.254.169.254, every host IPv4 address (published
#   host ports, e.g. the API/DB), the docker bridge gateway, and the other sandbox's IP.
# Prints PASS (unreachable: no route / timeout) or FAIL (reachable, including connection refused,
# which proves the packet reached the host) per target; exit code 1 if ANY target is reachable.
# Run it before and after scripts/sandbox_firewall.sh apply to see which layer blocks what.
set -uo pipefail

RUNTIME=${SANDBOX_RUNTIME:-runsc}
IMAGE=${IMAGE:-python:3.12-slim}
DOCKER=${DOCKER_BIN:-docker}
A=$(openssl rand -hex 8 2>/dev/null || date +%s%N | cut -c1-16)
B=$(openssl rand -hex 8 2>/dev/null || date +%s%N | rev | cut -c1-16)
NETA=bbsbx-$A; NETB=bbsbx-$B
EXP=$(( $(date +%s) + 600 ))
LAB=(--label bb.sandbox=1 --label "bb.sandbox.expires=$EXP")
cleanup() {
  "$DOCKER" rm -f -v "bbsbx-$A" "bbsbx-$B" >/dev/null 2>&1
  "$DOCKER" network rm "$NETA" "$NETB" >/dev/null 2>&1
}
trap cleanup EXIT
SEC=(--runtime "$RUNTIME" --pull never --read-only --cap-drop ALL --security-opt no-new-privileges --user 10001:10001 "${LAB[@]}")

"$DOCKER" network create --internal "${LAB[@]}" --label "bb.sandbox.id=$A" "$NETA" >/dev/null || exit 3
"$DOCKER" network create --internal "${LAB[@]}" --label "bb.sandbox.id=$B" "$NETB" >/dev/null || exit 3
"$DOCKER" run -d --name "bbsbx-$B" --network "$NETB" "${SEC[@]}" --label "bb.sandbox.id=$B" "$IMAGE" python -c "import time; time.sleep(300)" >/dev/null || exit 3
VICTIM=$("$DOCKER" inspect -f "{{(index .NetworkSettings.Networks \"$NETB\").IPAddress}}" "bbsbx-$B")
GW=$("$DOCKER" network inspect -f '{{(index .IPAM.Config 0).Gateway}}' "$NETA")
BRGW=$("$DOCKER" network inspect -f '{{(index .IPAM.Config 0).Gateway}}' bridge 2>/dev/null)
HOSTIPS=$(ip -o -4 addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | tr '\n' ' ')

TARGETS="gateway:$GW:80 metadata:169.254.169.254:80 bridge-gw:${BRGW:-172.17.0.1}:80 other-sandbox:$VICTIM:80"
for ip in $HOSTIPS; do for port in 22 5432 8000; do TARGETS="$TARGETS host-$ip:$ip:$port"; done; done

PROBE='
import socket, sys
bad = 0
for t in sys.argv[1:]:
    name, host, port = t.rsplit(":", 2) if t.count(":") >= 2 else (t, t, "80")
    s = socket.socket(); s.settimeout(2)
    try:
        s.connect((host, int(port))); print("FAIL", name, host + ":" + port, "reachable"); bad += 1
    except ConnectionRefusedError as e:  # an RST means the packet reached the target: reachable
        print("FAIL", name, host + ":" + port, "reachable at network level (port closed, RST)"); bad += 1
    except OSError as e:
        print("PASS", name, host + ":" + port, "blocked (%s)" % (e.__class__.__name__ + ":" + str(e.errno)))
sys.exit(1 if bad else 0)
'
"$DOCKER" run --rm --name "bbsbx-$A" --network "$NETA" "${SEC[@]}" --label "bb.sandbox.id=$A" \
  "$IMAGE" python -c "$PROBE" $TARGETS
rc=$?
[ $rc -eq 0 ] && echo "RESULT: all targets unreachable" || echo "RESULT: at least one target REACHABLE (or run failed), rc=$rc"
exit $rc
