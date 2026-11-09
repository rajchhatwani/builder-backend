"""Dedicated subnet pool for sandbox networks (CP-4B, firewall gap).

Every sandbox network is created with an explicit --subnet taken from ONE configured range
(default 172.30.0.0/16, split into /28 blocks). The host firewall (scripts/sandbox_firewall.sh)
matches that whole range by source address, so a network created after the firewall was applied is
covered with no `reapply`. Pure functions only: no docker, no I/O.
"""

import ipaddress
import secrets
from collections.abc import Iterable

from app.services.sandbox.base import SandboxError

IPv4Net = ipaddress.IPv4Network


def parse_pool(pool: str, prefix: int) -> IPv4Net:
    """Validate the configured pool: private IPv4, at least /12 .. /24 wide, blocks fit inside."""
    try:
        net = ipaddress.ip_network(pool, strict=True)
    except ValueError as exc:
        raise SandboxError(f"invalid sandbox subnet pool: {exc}") from exc
    if not isinstance(net, ipaddress.IPv4Network):
        raise SandboxError("sandbox subnet pool must be IPv4")
    if not net.is_private or net.is_link_local or net.is_loopback:
        raise SandboxError("sandbox subnet pool must be a private range")
    if not 16 <= prefix <= 29:
        raise SandboxError("sandbox subnet prefix must be between /16 and /29")
    if net.prefixlen > prefix - 2 or net.prefixlen < 12:
        raise SandboxError("sandbox subnet pool must be /12../(block prefix - 2)")
    return net


def parse_used(texts: Iterable[str]) -> list[IPv4Net]:
    """Subnets already taken on the host (any docker network); unparsable words are ignored."""
    used: list[IPv4Net] = []
    for word in texts:
        try:
            net = ipaddress.ip_network(word.strip(), strict=False)
        except ValueError:
            continue
        if isinstance(net, ipaddress.IPv4Network):
            used.append(net)
    return used


def pick_subnet(
    pool: IPv4Net, prefix: int, used: Iterable[IPv4Net], *, start: int | None = None
) -> str:
    """A free block of the pool, starting at a random offset so concurrent creators rarely clash
    (a clash is caught by docker's overlap error and retried). Raises when the pool is full."""
    taken = list(used)
    blocks = 1 << (prefix - pool.prefixlen)
    first = secrets.randbelow(blocks) if start is None else start % blocks
    size = 1 << (32 - prefix)
    base = int(pool.network_address)
    for i in range(blocks):
        cand = IPv4Net((base + ((first + i) % blocks) * size, prefix))
        if not any(cand.overlaps(t) for t in taken):
            return str(cand)
    raise SandboxError("sandbox subnet pool is exhausted")
