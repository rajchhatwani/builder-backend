"""MCP server mounted at /mcp (Streamable HTTP transport, mcp 2.x).

Auth: Bearer PAT with mcp:read / mcp:write / mcp:generate scopes extracted from
the HTTP Authorization header that MCPServer surfaces via ctx.headers.

Every tool call:
  1. Extracts Bearer token from ctx.headers["authorization"]
  2. Resolves the Principal (validates token, checks active user)
  3. Checks required MCP scope for the tool category
  4. Delegates to McpService which checks membership + mcp_enabled + role

Security:
  - This endpoint is NOT behind the standard REST guard (which is project-route-aware).
  - Destructive ops (delete entity, delete project) are deliberately not exposed.
  - All output is capped + control-chars stripped in McpService._cap().
  - Every call is audited with action="mcp.tool_call".

The MCP Starlette app is built once via build_mcp_app() and mounted in app/main.py.
"""

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import platform_authz as authz
from app.exceptions import AppError
from app.services.access_service import Principal, principal_from_api_token

try:
    from mcp.server.mcpserver import Context, MCPServer

    _MCP_AVAILABLE = True
except ImportError:  # pragma: no cover
    _MCP_AVAILABLE = False
    MCPServer = None  # type: ignore[assignment,misc]
    Context = None  # type: ignore[assignment,misc]


# ── Lifespan context ──────────────────────────────────────────────────────────────────


@dataclass
class McpLifespan:
    """Passed to every tool via ctx.request_context.lifespan_context."""

    session_factory: Any  # callable() -> AsyncContextManager[AsyncSession]


def _make_lifespan(session_factory: Any) -> Any:
    @asynccontextmanager
    async def lifespan(server: Any) -> Any:
        yield McpLifespan(session_factory=session_factory)

    return lifespan


# ── Auth helper ───────────────────────────────────────────────────────────────────────


def _extract_token(ctx: Any) -> str:
    """Pull Bearer token from Authorization header (case-insensitive)."""
    headers = ctx.headers or {}
    auth_header = ""
    for k, v in headers.items():
        if k.lower() == "authorization":
            auth_header = v
            break
    if not auth_header:
        raise AppError(
            code="unauthenticated",
            message="Authorization header with Bearer token required",
            status_code=401,
        )
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AppError(
            code="unauthenticated",
            message="Expected: Authorization: Bearer <token>",
            status_code=401,
        )
    return token.strip()


async def _auth(ctx: Any, db: AsyncSession, required_scope: str) -> Principal:
    """Resolve principal from token and check MCP scope."""
    token = _extract_token(ctx)
    if not token.startswith("bb_pat_"):
        raise AppError(
            code="unauthenticated",
            message="Only API tokens (bb_pat_...) are accepted by the MCP endpoint",
            status_code=401,
        )
    principal = await principal_from_api_token(db, token)
    if principal is None:
        raise AppError(
            code="unauthenticated",
            message="Invalid, expired or revoked API token",
            status_code=401,
        )
    if not authz.scopes_allow(principal.scopes, required_scope):
        raise AppError(
            code="insufficient_scope",
            message=f"This tool requires the '{required_scope}' scope on your API token",
            status_code=403,
        )
    return principal


# ── App factory ───────────────────────────────────────────────────────────────────────


def mcp_allowed_hosts(settings: Any) -> list[str]:
    """Host header values /mcp accepts: localhost, the public API host, and configured extras."""
    from urllib.parse import urlparse

    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    public = urlparse(str(settings.public_api_url)).hostname
    if public:
        hosts += [public, f"{public}:*"]
    for extra in settings.mcp_allowed_hosts:
        extra = extra.strip().lower()
        if extra:
            hosts += [extra] if ":" in extra else [extra, f"{extra}:*"]
    return hosts


def build_mcp_app(session_factory: Any, settings: Any = None) -> Any:
    """Build and return the MCP Starlette app. Called once at startup in app/main.py."""
    if settings is None:
        from app.config import get_settings

        settings = get_settings()
    if not _MCP_AVAILABLE:  # pragma: no cover
        raise RuntimeError("mcp package not installed; run: uv add 'mcp>=2.0'")

    from app.services.mcp_service import McpService

    mcp = MCPServer(
        name="BackendBuilder",
        instructions=(
            "BackendBuilder MCP server. "
            "Start with list_projects to discover projects you have access to. "
            "All tools are project-scoped. "
            "Authenticate with a Bearer API token (mcp:read scope required; "
            "mcp:write for write tools; mcp:generate for generate_project)."
        ),
        lifespan=_make_lifespan(session_factory),
    )

    # ── Read tools (scope: mcp:read) ──────────────────────────────────────────────────

    def _lifespan(ctx: "Context") -> McpLifespan:
        return ctx.request_context.lifespan_context  # type: ignore[return-value]

    @mcp.tool(description="List all projects where you have MCP access enabled.")
    async def list_projects(ctx: Context) -> list[dict[str, Any]]:
        async with _lifespan(ctx).session_factory() as db:
            principal = await _auth(ctx, db, authz.SCOPE_MCP_READ)
            return await McpService(db).list_projects(principal)

    @mcp.tool(description="Get the full spec for a project (entities, fields, relations, config).")
    async def get_project_spec(project_id: str, ctx: Context) -> dict[str, Any]:
        async with _lifespan(ctx).session_factory() as db:
            principal = await _auth(ctx, db, authz.SCOPE_MCP_READ)
            return await McpService(db).get_project_spec(principal, uuid.UUID(project_id))

    @mcp.tool(description="Get the data model (entities, fields, relations) for a project.")
    async def get_data_model(project_id: str, ctx: Context) -> dict[str, Any]:
        async with _lifespan(ctx).session_factory() as db:
            principal = await _auth(ctx, db, authz.SCOPE_MCP_READ)
            return await McpService(db).get_data_model(principal, uuid.UUID(project_id))

    @mcp.tool(description="Get the generated project's OpenAPI 3.1 spec.")
    async def get_openapi(project_id: str, ctx: Context) -> dict[str, Any]:
        async with _lifespan(ctx).session_factory() as db:
            principal = await _auth(ctx, db, authz.SCOPE_MCP_READ)
            return await McpService(db).get_openapi(principal, uuid.UUID(project_id))

    @mcp.tool(
        description=(
            "Get authentication configuration for a project (provider, flows, token format)."
        )
    )
    async def get_auth_model(project_id: str, ctx: Context) -> dict[str, Any]:
        async with _lifespan(ctx).session_factory() as db:
            principal = await _auth(ctx, db, authz.SCOPE_MCP_READ)
            return await McpService(db).get_auth_model(principal, uuid.UUID(project_id))

    @mcp.tool(
        description=(
            "Get the frontend contract: routes, auth flow, pagination conventions, "
            "error shapes, and roles. Use this to wire up a dashboard correctly."
        )
    )
    async def get_frontend_contract(project_id: str, ctx: Context) -> dict[str, Any]:
        async with _lifespan(ctx).session_factory() as db:
            principal = await _auth(ctx, db, authz.SCOPE_MCP_READ)
            return await McpService(db).get_frontend_contract(principal, uuid.UUID(project_id))

    @mcp.tool(
        description=(
            "Get deployment configuration for a project "
            "(cloud, region, environments). No secrets returned."
        )
    )
    async def get_deploy_info(project_id: str, ctx: Context) -> dict[str, Any]:
        async with _lifespan(ctx).session_factory() as db:
            principal = await _auth(ctx, db, authz.SCOPE_MCP_READ)
            return await McpService(db).get_deploy_info(principal, uuid.UUID(project_id))

    @mcp.tool(description="Validate the spec and return a list of issues.")
    async def validate_spec(project_id: str, ctx: Context) -> dict[str, Any]:
        async with _lifespan(ctx).session_factory() as db:
            principal = await _auth(ctx, db, authz.SCOPE_MCP_READ)
            return await McpService(db).validate_spec(principal, uuid.UUID(project_id))

    # ── Write tools (scope: mcp:write, requires editor+ role) ────────────────────────

    @mcp.tool(
        description=("Create a new entity in a project. Requires mcp:write scope and editor+ role.")
    )
    async def create_entity(
        project_id: str,
        name: str,
        description: str = "",
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        async with _lifespan(ctx).session_factory() as db:
            principal = await _auth(ctx, db, authz.SCOPE_MCP_WRITE)
            return await McpService(db).create_entity(
                principal, uuid.UUID(project_id), name, description
            )

    @mcp.tool(
        description=(
            "Add a field to an entity. field dict keys: name (str), type (string|integer|boolean|"
            "float|decimal|date|datetime|text|uuid|json|enum), required (bool, default false), "
            "unique (bool), indexed (bool). Requires mcp:write scope and editor+ role."
        )
    )
    async def add_field(
        project_id: str,
        entity_name: str,
        field: dict[str, Any],
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        async with _lifespan(ctx).session_factory() as db:
            principal = await _auth(ctx, db, authz.SCOPE_MCP_WRITE)
            return await McpService(db).add_field(
                principal, uuid.UUID(project_id), entity_name, field
            )

    @mcp.tool(
        description=(
            "Add a relation between entities. relation dict keys: "
            "kind (one_to_many|many_to_many|one_to_one), "
            "from_entity_id (uuid), to_entity_id (uuid), "
            "from_name (str), to_name (str). "
            "Requires mcp:write scope and editor+ role."
        )
    )
    async def add_relation(
        project_id: str,
        relation: dict[str, Any],
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        async with _lifespan(ctx).session_factory() as db:
            principal = await _auth(ctx, db, authz.SCOPE_MCP_WRITE)
            return await McpService(db).add_relation(principal, uuid.UUID(project_id), relation)

    @mcp.tool(
        description=(
            "Record intended RBAC permissions for an entity operation. "
            "Requires mcp:write scope and editor+ role. "
            "Use PUT /projects/{id}/authorization to persist full policy changes."
        )
    )
    async def set_permissions(
        project_id: str,
        entity_name: str,
        operation: str,
        roles: list[str],
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        async with _lifespan(ctx).session_factory() as db:
            principal = await _auth(ctx, db, authz.SCOPE_MCP_WRITE)
            return await McpService(db).set_permissions(
                principal, uuid.UUID(project_id), entity_name, operation, roles
            )

    # ── Generate tool (scope: mcp:generate) ──────────────────────────────────────────

    @mcp.tool(
        description=(
            "Generate the project zip. Returns a download_url to fetch the zip "
            "with your API token. Requires mcp:generate scope and editor+ role. "
            "The zip is never returned inline — download it separately."
        )
    )
    async def generate_project(
        project_id: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        async with _lifespan(ctx).session_factory() as db:
            principal = await _auth(ctx, db, authz.SCOPE_MCP_GENERATE)
            return await McpService(db).generate_project(principal, uuid.UUID(project_id))

    # Build and return the Starlette app (streamable HTTP transport).
    # The outer FastAPI app mounts this under `/mcp`, so the inner path is just `/`
    # — otherwise the real endpoint would be `/mcp/mcp`.
    from mcp.server.transport_security import TransportSecuritySettings

    return mcp.streamable_http_app(
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=mcp_allowed_hosts(settings),
            allowed_origins=[],
        ),
    )
