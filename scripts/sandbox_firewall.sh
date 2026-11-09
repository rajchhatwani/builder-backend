#!/usr/bin/env bash
# Host firewall for sandbox networks (backlog P2). REQUIRES ROOT and refuses to run without --yes.
#
# Usage: sudo scripts/sandbox_firewall.sh apply|reapply|remove|status --yes
#
# What it does: installs a chain BB-SANDBOX in the DOCKER-USER chain (iptables, which Docker evaluates
# before its own rules; for nftables-only hosts the iptables-nft shim is used). Traffic whose source is
# a bb sandbox network is dropped when its destination is the cloud metadata IP 169.254.169.254, any
# link-local address, the host's own addresses / bridge gateways, or any private range (10/8, 172.16/12,
# 192.168/16, 100.64/10) - except traffic that stays inside the same bridge (same -i/-o interface),
# which Docker already scopes to the one network. Sandbox networks are --internal (no egress at all);
# this is the second layer if one is ever created without that flag or a runtime bug opens a path.
#
# Traffic from a sandbox to the HOST itself (its bridge gateway, published ports on any host IP) never
# crosses DOCKER-USER (it is INPUT, not FORWARD), so a second chain BB-SANDBOX-IN is hooked into INPUT
# and drops everything arriving from a sandbox bridge.
#
# Sandbox bridges are found by their label bb.sandbox=1 (docker network ls).
# KNOWN LIMIT (S-2): rules match concrete bridge names (br-<id>), because "br-+" would also hit every
# non-sandbox Docker network and there is no dedicated subnet pool yet. A preview network created AFTER
# `apply` is NOT covered until `reapply` runs. `reapply` (same as `apply`) builds the complete new chains
# under temporary names, hooks them in first, unhooks the old ones, deletes only our own old chains and
# renames the new ones, so there is no unprotected gap. Run it after new preview networks appear (cron or
# the runner reaper); scripts/golive_check.sh prints this reminder. Foreign rules are never flushed.
# Both chains start with `-m conntrack --ctstate ESTABLISHED,RELATED -j RETURN` (replies to connections the
# host/API opened must pass); only NEW connections from a sandbox bridge are dropped (S-1).
# After apply, prove it with scripts/sandbox_hostile_check.sh AND a real preview request (not run as non-root).
set -euo pipefail

CHAIN=BB-SANDBOX
DOCKER_BIN=${DOCKER_BIN:-docker}
PRIVATE="10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 169.254.0.0/16"

usage() { echo "usage: sudo $0 apply|reapply|remove|status --yes   (needs root)"; exit 2; }
[ $# -ge 1 ] || usage
cmd=$1; shift
yes=0; for a in "$@"; do [ "$a" = "--yes" ] && yes=1; done
[ "$cmd" = status ] || [ "$yes" = 1 ] || { echo "refusing without --yes" >&2; usage; }
[ "$(id -u)" = 0 ] || { echo "this script needs root (iptables); re-run with sudo" >&2; exit 1; }
command -v iptables >/dev/null || { echo "iptables not found" >&2; exit 1; }

bridges() {  # one bridge interface name per sandbox network
  for id in $("$DOCKER_BIN" network ls -q --filter label=bb.sandbox=1); do
    echo "br-${id:0:12}"
  done
}
host_ips() { ip -o -4 addr show scope global | awk '{print $4}' | cut -d/ -f1; }

flush() {
  iptables -D INPUT -j "$CHAIN-IN" 2>/dev/null || true
  iptables -F "$CHAIN-IN" 2>/dev/null || true
  iptables -X "$CHAIN-IN" 2>/dev/null || true
  iptables -D DOCKER-USER -j "$CHAIN" 2>/dev/null || true
  iptables -F "$CHAIN" 2>/dev/null || true
  iptables -X "$CHAIN" 2>/dev/null || true
}

case "$cmd" in
  apply|reapply)
    NEW="$CHAIN-N"; NEWIN="$CHAIN-IN-N"
    # leftovers of an interrupted run (our own temp chains only)
    iptables -F "$NEW" 2>/dev/null || true; iptables -X "$NEW" 2>/dev/null || true
    iptables -F "$NEWIN" 2>/dev/null || true; iptables -X "$NEWIN" 2>/dev/null || true
    iptables -N "$NEW"
    iptables -N "$NEWIN"
    iptables -A "$NEWIN" -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
    iptables -A "$NEW" -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
    for br in $(bridges); do
      # Same-network traffic stays (in and out on the same bridge).
      iptables -A "$NEWIN" -i "$br" -m conntrack --ctstate NEW -j DROP
      iptables -A "$NEW" -i "$br" -o "$br" -j RETURN
      iptables -A "$NEW" -i "$br" -d 169.254.169.254/32 -m conntrack --ctstate NEW -j DROP
      for ip in $(host_ips); do iptables -A "$NEW" -i "$br" -d "$ip/32" -m conntrack --ctstate NEW -j DROP; done
      for net in $PRIVATE; do iptables -A "$NEW" -i "$br" -d "$net" -m conntrack --ctstate NEW -j DROP; done
    done
    iptables -A "$NEW" -j RETURN
    iptables -A "$NEWIN" -j RETURN
    # swap with no gap: hook new, unhook old, drop old, rename new
    iptables -I DOCKER-USER 1 -j "$NEW"
    iptables -I INPUT 1 -j "$NEWIN"
    flush
    iptables -E "$NEW" "$CHAIN"
    iptables -E "$NEWIN" "$CHAIN-IN"
    echo "applied: $(bridges | wc -l) sandbox bridge(s) covered; later bridges need 'reapply'"
    ;;
  remove) flush; echo "removed" ;;
  status)
    if iptables -S "$CHAIN" 2>/dev/null; then
      iptables -S "$CHAIN-IN" 2>/dev/null
      { iptables -S DOCKER-USER | grep -q -- "-j $CHAIN\$" && iptables -S INPUT | grep -q -- "-j $CHAIN-IN\$"; } && echo "hooked into DOCKER-USER and INPUT" || echo "chains present but NOT hooked"
    else echo "not applied"; exit 1; fi ;;
  *) usage ;;
esac
