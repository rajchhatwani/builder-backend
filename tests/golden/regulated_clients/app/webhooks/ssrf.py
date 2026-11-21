"""The SSRF guard for outgoing webhooks (generated). Default deny: a destination is allowed only when
EVERY check passes; anything unusual is refused rather than interpreted.

* only http / https (http only when the spec says `allow_http`), no user info, no control characters,
  no backslashes, no fragments, a bounded length;
* the port must be on the allow-list (default: 443, plus 80 with `allow_http`), never an internal-service port;
* the host is a DNS name or a CANONICAL IP literal. Decimal / hex / octal / short forms of an IPv4 address
  (`2130706433`, `0x7f.1`, `0177.0.0.1`) are refused outright, so no parser disagreement can hide a private
  address;
* the address(es) must be globally routable: private, loopback, link-local (cloud metadata 169.254.169.254),
  carrier-grade NAT, multicast, reserved, unspecified are refused, IPv4 and IPv6, and an IPv4 address
  embedded in an IPv6 one (::ffff:a.b.c.d, 64:ff9b::/96, 2002::/16) is judged as that IPv4 address; Teredo is refused;
* DNS is resolved HERE, every answer is checked (one bad record refuses the host), and the caller connects to the
  chosen IP literally (`pin`): the name is never resolved a second time, so a DNS-rebinding answer cannot swap
  in an internal address between the check and the connect.
"""

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import SplitResult, quote, urlsplit

MAX_URL_LENGTH = 2048
_CONTROL = re.compile(r"[\x00-\x20\x7f-\x9f\\]")  # spaces, control characters, backslash
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_BLOCKED_SUFFIXES = (
    ".localhost", ".local", ".localdomain", ".internal", ".intranet", ".lan", ".home", ".corp", ".private",
    ".home.arpa", ".in-addr.arpa", ".ip6.arpa",
)  # fmt: skip
_BLOCKED_NAMES = frozenset({"localhost", "metadata", "metadata.google.internal", "instance-data"})

# Version-independent deny list (Python's is_global changes between releases).
_V4_DENY = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
        "192.0.0.0/24", "192.0.2.0/24", "192.88.99.0/24", "192.168.0.0/16", "198.18.0.0/15",
        "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4",
    )
)  # fmt: skip
_V6_DENY = tuple(
    ipaddress.ip_network(n)
    for n in (
        "::/128", "::1/128", "100::/64", "5f00::/16", "2001:10::/28", "2001:20::/28", "2001::/32", "2001:db8::/32", "fc00::/7", "fe80::/10", "fec0::/10",
        "ff00::/8",
    )
)  # fmt: skip


class Blocked(Exception):
    """The destination is refused. `code` is stable and safe to log; the message never holds the URL."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ResolveFailed(Exception):
    """DNS gave no answer (temporary: the delivery may be tried again)."""


@dataclass(frozen=True)
class Policy:
    allow_http: bool
    allowed_ports: tuple[int, ...]  # empty = 443 (+ 80 when allow_http)


@dataclass(frozen=True)
class Target:
    scheme: str
    host: str  # lower-case ASCII name, or a canonical IP literal
    port: int
    request_target: str  # path and query, percent-encoded
    is_ip: bool

    @property
    def host_header(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        default = 443 if self.scheme == "https" else 80
        return host if self.port == default else f"{host}:{self.port}"


def ports_for(policy: Policy) -> tuple[int, ...]:
    if policy.allowed_ports:
        return policy.allowed_ports
    return (443, 80) if policy.allow_http else (443,)


def _embedded_v4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip in ipaddress.ip_network("64:ff9b::/96"):  # NAT64
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    if ip in ipaddress.ip_network("2002::/16"):  # 6to4
        return ipaddress.IPv4Address((int(ip) >> 80) & 0xFFFFFFFF)
    if ip in ipaddress.ip_network("::ffff:0:0:0/96"):  # IPv4-translated (SIIT)
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    if ip in ipaddress.ip_network("::/96"):  # IPv4-compatible (deprecated)
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True only for a globally routable unicast address."""
    if isinstance(ip, ipaddress.IPv6Address):
        inner = _embedded_v4(ip)
        if inner is not None:
            return is_public_ip(inner)
        if any(ip in net for net in _V6_DENY):
            return False
        return bool(ip.is_global) and not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast)
    if any(ip in net for net in _V4_DENY):
        return False
    return bool(ip.is_global)


def _canonical_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """The address when `host` is an IP literal; None when it is a name. A literal that is not in canonical
    form (and anything inet_aton would read as an address) raises Blocked."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if str(ip) != host:
            raise Blocked("ip_not_canonical")
        return ip
    if "%" in host or ":" in host:
        raise Blocked("invalid_host")  # a zone id, or something that is not an IPv6 literal
    try:
        socket.inet_aton(host)  # decimal, hex, octal and short forms
    except OSError:
        return None
    raise Blocked("ip_not_canonical")


def parse_target(url: str, policy: Policy) -> Target:
    """Syntax checks only (no network). Raises Blocked."""
    if not isinstance(url, str) or not url or len(url) > MAX_URL_LENGTH:
        raise Blocked("invalid_url")
    if _CONTROL.search(url) or not url.isascii():
        raise Blocked("invalid_url")
    try:
        parts: SplitResult = urlsplit(url)
        port = parts.port
        host = parts.hostname
    except ValueError:
        raise Blocked("invalid_url") from None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or (scheme == "http" and not policy.allow_http):
        raise Blocked("scheme_not_allowed")
    if "@" in parts.netloc or parts.username is not None or parts.password is not None:
        raise Blocked("userinfo_not_allowed")
    if parts.fragment or "#" in url:
        raise Blocked("invalid_url")
    if not host:
        raise Blocked("invalid_host")
    if "%" in host:
        raise Blocked("invalid_host")
    host = host.lower().rstrip(".")
    effective = port if port is not None else (443 if scheme == "https" else 80)
    if effective not in ports_for(policy):
        raise Blocked("port_not_allowed")
    ip = _canonical_ip(host)
    if ip is not None:
        if not is_public_ip(ip):
            raise Blocked("address_not_public")
        host, is_ip = str(ip), True
    else:
        if len(host) > 253 or host in _BLOCKED_NAMES or host.endswith(_BLOCKED_SUFFIXES):
            raise Blocked("host_not_allowed")
        labels = host.split(".")
        if len(labels) < 2 or not all(_LABEL.match(label) for label in labels):
            raise Blocked("invalid_host")  # also refuses xn-- tricks that are not plain ASCII labels
        if labels[-1].isdigit():
            raise Blocked("invalid_host")
        is_ip = False
    path = quote(parts.path or "/", safe="/:@!$&'()*+,;=-._~%")
    target = path + ("?" + quote(parts.query, safe="/:@!$&'()*+,;=-._~%?") if parts.query else "")
    return Target(scheme=scheme, host=host, port=effective, request_target=target, is_ip=is_ip)


Resolver = Callable[[str, int], Awaitable[list[str]]]


async def system_resolver(host: str, port: int) -> list[str]:
    """Every address the system resolver returns for `host` (A and AAAA)."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise ResolveFailed("dns") from None
    return [str(info[4][0]) for info in infos]


RESOLVER: Resolver = system_resolver  # tests replace it; production never does


async def pin(target: Target) -> str:
    """The IP address to connect to. Resolves once, refuses the host if ANY answer is not public."""
    if target.is_ip:
        return target.host
    answers = await RESOLVER(target.host, target.port)
    if not answers:
        raise ResolveFailed("dns")
    chosen: str | None = None
    for raw in answers:
        try:
            ip = ipaddress.ip_address(raw.split("%", 1)[0])
        except ValueError:
            raise Blocked("address_not_public") from None
        if not is_public_ip(ip):
            raise Blocked("address_not_public")
        chosen = chosen or str(ip)
    assert chosen is not None
    return chosen
