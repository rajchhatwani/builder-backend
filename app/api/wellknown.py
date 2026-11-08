"""RFC 9728 protected-resource metadata endpoint.

Advertises that this server accepts Bearer PATs (not OAuth 2.1 redirect flow in v1).
MCP clients that follow the spec will fetch this before attempting OAuth and discover
that the simpler PAT bearer approach is supported.
"""

from fastapi import APIRouter

from app.core import platform_authz as authz

router = APIRouter(tags=["discovery"])


@router.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource() -> dict[str, object]:
    """RFC 9728 protected-resource metadata. No auth required."""
    return {
        "resource": "/",
        "bearer_methods_supported": ["header"],
        "authorization_servers": [],
        "scopes_supported": sorted(authz.VALID_SCOPES),
        "mcp_endpoint": "/mcp",
    }
