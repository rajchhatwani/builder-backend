#!/usr/bin/env bash
# Host firewall for sandbox networks (backlog P2). REQUIRES ROOT and refuses to run without --yes.
#
# Usage: sudo scripts/sandbox_firewall.sh apply|reapply|remove|status --yes
#   env: SANDBOX_SUBNET_POOL (default 172.30.0.0/16) must equal Settings.sandbox_subnet_pool.
#
# What it does: installs a chain BB-SANDBOX in the DOCKER-USER chain (iptables, which Docker evaluates
# before its own rules; for nftables-only hosts the iptables-nft shim is used). The platform creates
# EVERY sandbox network on an explicit --subnet taken from the dedicated pool (CP-4B), so the rules
# match that range by SOURCE ADDRESS, not per bridge: a sandbox network created after `apply` is covered
# at once, no `reapply` needed. Traffic whose source is in the pool is dropped (NEW connections only)
# when its destination is the cloud metadata IP 169.254.169.254, any host address, another sandbox, or
# any private range (10/8, 172.16/12, 192.168/16, 100.64/10, 169.254/16) - except traffic that stays
# inside one bridge (iptables physdev "bridged": Docker already scopes it to the one network).
# Sandbox networks are --internal (no egress at all). This script blocks sandbox -> host / other sandbox /
# metadata / private ranges; it does NOT block sandbox -> public internet (only --internal does that).
#
# Traffic from a sandbox to the HOST itself (its bridge gateway, published ports on any host IP) never
# crosses DOCKER-USER (it is INPUT, not FORWARD), so a second chain BB-SANDBOX-IN is hooked into INPUT
# and drops every NEW connection whose source is in the pool.
#
# Needs the pool to be unused by anything else: keep Docker's default-address-pools (daemon.json) and
# the LAN away from it. `apply` warns when a non-sandbox docker network sits inside the pool.
# `reapply` (same as `apply`) builds the complete new chains under temporary names, hooks them in first,
# unhooks the old ones, deletes only our own old chains and renames the new ones, so there is no
# unprotected gap. Foreign rules are never flushed. Both chains start with
# `-m conntrack --ctstate ESTABLISHED,RELATED -j RETURN` (replies to connections the host/API opened
# must pass); only NEW connections from a sandbox address are dropped (S-1).
# After apply, prove it with scripts/sandbox_hostile_check.sh (NO reapply in between) AND a real preview
# request (not run as non-root).
set -euo pipefail

CHAIN=BB-SANDBOX
DOCKER_BIN=${DOCKER_BIN:-docker}
POOL=${SANDBOX_SUBNET_POOL:-172.30.0.0/16}
PRIVATE="10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 169.254.0.0/16"

usage() { echo "usage: sudo $0 apply|reapply|remove|status --yes   (needs root)"; exit 2; }
[ $# -ge 1 ] || usage
cmd=$1; shift
yes=0; for a in "$@"; do [ "$a" = "--yes" ] && yes=1; done
[ "$cmd" = status ] || [ "$yes" = 1 ] || { echo "refusing without --yes" >&2; usage; }
[ "$(id -u)" = 0 ] || { echo "this script needs root (iptables); re-run with sudo" >&2; exit 1; }
command -v iptables >/dev/null || { echo "iptables not found" >&2; exit 1; }

case "$POOL" in *[!0-9./]*|"") echo "invalid SANDBOX_SUBNET_POOL" >&2; exit 1 ;; esac
sandbox_networks() { "$DOCKER_BIN" network ls -q --filter label=bb.sandbox=1 | wc -l; }
foreign_in_pool() {  # non-sandbox docker networks whose subnet starts with the pool's first two octets
  local pre; pre=$(echo "$POOL" | cut -d. -f1-2)
  for id in $("$DOCKER_BIN" network ls -q); do
    "$DOCKER_BIN" network inspect "$id" --format '{{.Name}}|{{index .Labels "bb.sandbox"}}|{{range .IPAM.Config}}{{.Subnet}} {{end}}' 2>/dev/null
  done | awk -F'|' -v pre="$pre" '$2=="" && index($3, pre ".")==1 {print $1}'
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
    # Same-bridge traffic stays (bridged by br_netfilter; routed cross-network traffic is not bridged).
    iptables -A "$NEW" -s "$POOL" -d "$POOL" -m physdev --physdev-is-bridged -j RETURN
    iptables -A "$NEW" -s "$POOL" -d "$POOL" -m conntrack --ctstate NEW -j DROP
    iptables -A "$NEWIN" -s "$POOL" -m conntrack --ctstate NEW -j DROP
    iptables -A "$NEW" -s "$POOL" -d 169.254.169.254/32 -m conntrack --ctstate NEW -j DROP
    for ip in $(host_ips); do iptables -A "$NEW" -s "$POOL" -d "$ip/32" -m conntrack --ctstate NEW -j DROP; done
    for net in $PRIVATE; do iptables -A "$NEW" -s "$POOL" -d "$net" -m conntrack --ctstate NEW -j DROP; done
    iptables -A "$NEW" -j RETURN
    iptables -A "$NEWIN" -j RETURN
    # swap with no gap: hook new, unhook old, drop old, rename new
    iptables -I DOCKER-USER 1 -j "$NEW"
    iptables -I INPUT 1 -j "$NEWIN"
    flush
    iptables -E "$NEW" "$CHAIN"
    iptables -E "$NEWIN" "$CHAIN-IN"
    echo "applied: sandbox pool $POOL covered by range ($(sandbox_networks) sandbox network(s) now; later ones need no reapply)"
    for n in $(foreign_in_pool); do echo "WARNING: non-sandbox docker network '$n' lies inside $POOL; its traffic is filtered too. Move it or the pool." >&2; done
    ;;
  remove) flush; echo "removed" ;;
  status)
    if iptables -S "$CHAIN" 2>/dev/null; then
      iptables -S "$CHAIN-IN" 2>/dev/null
      iptables -S "$CHAIN" | grep -q -- "-s $POOL " || echo "WARNING: chain does not match pool $POOL (SANDBOX_SUBNET_POOL differs from what was applied)"
      { iptables -S DOCKER-USER | grep -q -- "-j $CHAIN\$" && iptables -S INPUT | grep -q -- "-j $CHAIN-IN\$"; } && echo "hooked into DOCKER-USER and INPUT" || echo "chains present but NOT hooked"
    else echo "not applied"; exit 1; fi ;;
  *) usage ;;
esac
