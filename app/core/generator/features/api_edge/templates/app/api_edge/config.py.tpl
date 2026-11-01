"""API edge settings read from the environment (generated). A bad value stops the process."""

import functools
import ipaddress
import os

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


@functools.lru_cache(maxsize=1)
def _parse(raw: str) -> tuple[Network, ...]:
    networks: list[Network] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            raise ValueError(f"API_EDGE_TRUSTED_PROXIES: {part!r} is not an IP address or network") from None
    return tuple(networks)


def trusted_proxies() -> tuple[Network, ...]:
    """API_EDGE_TRUSTED_PROXIES: comma-separated addresses / networks of the proxies in front of the
    app. Empty (the default) means X-Forwarded-For is never read: the client is the direct peer."""
    return _parse(os.environ.get("API_EDGE_TRUSTED_PROXIES", ""))
