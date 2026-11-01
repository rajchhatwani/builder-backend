"""Who is calling, and from where (generated).

A caller is keyed by user and tenant ids, never by a token. The client address is the direct peer
unless API_EDGE_TRUSTED_PROXIES names the proxies in front of the app."""

import dataclasses
import ipaddress

from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_edge import config
from app.auth.deps import get_current_user
from app.core.errors import AppError

NO_TENANT = "-"


@dataclasses.dataclass(frozen=True)
class Caller:
    tenant_key: str  # the tenant id, or "-" when there is none
    principal_key: str  # "user:<id>", or "ip:<address>" for a caller without a valid token
    authenticated: bool
    ip: str


def _address(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(text.strip())
    except ValueError:
        return None


def client_ip(request: Request) -> str:
    """The direct peer; X-Forwarded-For is read only when the peer is a trusted proxy, and then only
    the right-most entry that is not itself a trusted proxy counts (the rest can be forged)."""
    peer = request.client.host if request.client else None
    peer_ip = _address(peer) if peer else None
    if peer_ip is None:
        return "unknown"
    trusted = config.trusted_proxies()
    if not trusted or not any(peer_ip in net for net in trusted):
        return str(peer_ip)
    entries = [e for e in request.headers.get("x-forwarded-for", "").split(",") if e.strip()]
    for entry in reversed(entries):
        address = _address(entry)
        if address is None:
            return str(peer_ip)  # garbage in the header: do not guess
        if not any(address in net for net in trusted):
            return str(address)
    return str(peer_ip)


async def resolve(request: Request, session: AsyncSession) -> Caller:
    ip = client_ip(request)
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        try:
            user = await get_current_user(
                request, session, HTTPAuthorizationCredentials(scheme="Bearer", credentials=token.strip())
            )
        except AppError:
            user = None  # a bad token is the route's business (401 where it matters): limit it by address
        if user is not None:
            tenant_id = getattr(user, "tenant_id", None)
            return Caller(
                tenant_key=str(tenant_id) if tenant_id is not None else NO_TENANT,
                principal_key=f"user:{user.id}",
                authenticated=True,
                ip=ip,
            )
    return Caller(tenant_key=NO_TENANT, principal_key=f"ip:{ip}", authenticated=False, ip=ip)
