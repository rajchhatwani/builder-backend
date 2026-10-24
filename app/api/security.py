"""The request guard: every builder route passes through here before its handler runs.

`guard` is attached to every router except health and the sign-in endpoints (see app/main.py), so
a route added without thinking about access is still protected. If a route is neither about a
project nor on the short unscoped list in app.core.platform_authz, it is refused (fail closed);
tests/api/test_access_matrix.py walks the OpenAPI schema to make sure none exists.
"""

from collections.abc import Awaitable, Callable

import structlog
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core import platform_authz as authz
from app.core.ratelimit import SlidingWindowLimiter
from app.db import get_session
from app.exceptions import AppError
from app.models.enums import AuditResult, TokenAudience
from app.services import access_service, audit_service
from app.services.access_service import ROLE_LEVEL, Principal
from app.services.platform_auth_service import RequestInfo

log = structlog.get_logger()

_BEARER = {"WWW-Authenticate": "Bearer"}
_ID_PARAMS = (
    "project_id",
    "entity_id",
    "field_id",
    "relation_id",
    "role_id",
    "permission_id",
    "generation_id",
)


def unauthenticated() -> AppError:
    return AppError(
        code="unauthenticated",
        message="sign in to continue",
        status_code=401,
        headers=_BEARER,
    )


def not_found() -> AppError:
    return AppError(code="not_found", message="not found", status_code=404)


def forbidden(message: str = "you are not allowed to do that", code: str = "forbidden") -> AppError:
    return AppError(code=code, message=message, status_code=403)


# -- request facts ----------------------------------------------------------------------


def client_ip(request: Request, settings: Settings | None = None) -> str | None:
    """The caller's address. X-Forwarded-For is believed only when told a proxy sets it, and then
    only its last hop (the one our own proxy appended), never what the client put in front."""
    settings = settings or get_settings()
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()[:64] or None
    return request.client.host if request.client else None


def request_info(request: Request) -> RequestInfo:
    return RequestInfo(
        client_ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
        request_id=getattr(request.state, "request_id", None),
    )


_limiter: SlidingWindowLimiter | None = None


def auth_limiter() -> SlidingWindowLimiter:
    global _limiter  # noqa: PLW0603
    if _limiter is None:
        s = get_settings()
        _limiter = SlidingWindowLimiter(
            s.auth_rate_limit_attempts, s.auth_rate_limit_window_seconds
        )
    return _limiter


def reset_auth_limiter() -> None:
    """Tests only."""
    global _limiter  # noqa: PLW0603
    _limiter = None


async def rate_limit_auth(request: Request) -> None:
    """Dependency for sign-in style endpoints: per client address, before any work is done."""
    ip = client_ip(request) or "unknown"
    limiter = auth_limiter()
    if not limiter.allow(ip):
        raise AppError(
            code="rate_limited",
            message="too many attempts; wait a few minutes",
            status_code=429,
            headers={"Retry-After": str(limiter.retry_after(ip))},
        )


async def require_same_origin(request: Request) -> None:
    """Cookie-carrying endpoints (refresh, logout) need a header a cross-site form cannot send,
    and, when the browser names an Origin, one of ours. SameSite=Strict is the first layer."""
    if request.headers.get("x-requested-with") != "builder":
        raise forbidden("missing X-Requested-With header", "csrf_check_failed")
    origin = request.headers.get("origin")
    if origin is not None and origin not in get_settings().cors_origins:
        raise forbidden("origin not allowed", "csrf_check_failed")


# -- identity ---------------------------------------------------------------------------


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def _principal(request: Request, db: AsyncSession, audience: TokenAudience) -> Principal:
    token = _bearer_token(request)
    if token is None:
        raise unauthenticated()
    principal: Principal | None
    if token.startswith("bb_pat_"):
        # API tokens are for the customer surface only; the admin console never accepts them.
        principal = (
            await access_service.principal_from_api_token(db, token)
            if audience is TokenAudience.app
            else None
        )
    else:
        principal = await access_service.principal_from_jwt(db, token, audience)
    if principal is None:
        raise unauthenticated()
    request.state.principal = principal
    return principal


async def current_principal(request: Request, db: AsyncSession = Depends(get_session)) -> Principal:
    """Any valid customer-surface credential: a session token or an API token."""
    return await _principal(request, db, TokenAudience.app)


async def session_principal(request: Request, db: AsyncSession = Depends(get_session)) -> Principal:
    """A signed-in browser session only (no API tokens): for managing the account itself."""
    principal = await _principal(request, db, TokenAudience.app)
    if principal.via != "session":
        raise forbidden("this needs a signed-in session, not an API token", "session_required")
    return principal


async def guard(
    request: Request,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> Principal:
    """Authenticate, then authorise the request against the project it is about."""
    route = request.scope.get("route")
    template: str = getattr(route, "path", request.url.path)
    method = request.method.upper()
    user = principal.user

    if user.must_change_password:
        raise forbidden("choose a new password before continuing", "password_change_required")

    if principal.via == "api_token":
        needed_scope = authz.required_scope(method, template)
        if not authz.scopes_allow(principal.scopes, needed_scope):
            await _deny(db, request, principal, "scope", detail={"needed": needed_scope})
            raise forbidden(
                f"this API token lacks the '{needed_scope}' scope", "insufficient_scope"
            )

    if (method, template) in authz.UNSCOPED_ROUTES:
        # A pinned token may list (the list is cut down to its project) but never create projects.
        if principal.token_project_id is not None and method != "GET":
            raise forbidden("this API token is limited to one project", "insufficient_scope")
        return principal

    project_id = await access_service.project_of(db, template, dict(request.path_params))
    if project_id is None:
        if any(name in request.path_params for name in _ID_PARAMS):
            raise not_found()  # the id does not exist (or is malformed)
        # A route that is about no project and is not on the allow-list: a programming error.
        log.error("unscoped_route_refused", method=method, route=template)
        raise forbidden("this endpoint is not available", "unscoped_route")

    if principal.token_project_id is not None and principal.token_project_id != project_id:
        raise not_found()
    role = await access_service.member_role(db, user.id, project_id)
    if role is None:
        raise not_found()  # not a member: same answer as "does not exist"
    needed = authz.required_member_role(method, template)
    if ROLE_LEVEL[role] < ROLE_LEVEL[needed]:
        await _deny(
            db, request, principal, "role", project_id=project_id, detail={"needed": needed.value}
        )
        raise forbidden(f"this needs the project role '{needed.value}'")

    request.state.project_id = project_id
    request.state.member_role = role
    if method not in ("GET", "HEAD", "OPTIONS"):
        # Rides on the handler's own commit, so only changes that actually happened are recorded.
        await audit_service.record(
            db,
            action="project.change",
            actor_id=user.id,
            actor_email=user.email,
            via=principal.via,
            project_id=project_id,
            client_ip=client_ip(request),
            request_id=getattr(request.state, "request_id", None),
            detail={"method": method, "route": template},
        )
    return principal


async def _deny(
    db: AsyncSession,
    request: Request,
    principal: Principal,
    why: str,
    *,
    project_id: object = None,
    detail: dict[str, object] | None = None,
) -> None:
    await audit_service.record(
        db,
        action="access.denied",
        result=AuditResult.denied,
        actor_id=principal.user.id,
        actor_email=principal.user.email,
        via=principal.via,
        project_id=project_id,  # type: ignore[arg-type]
        client_ip=client_ip(request),
        request_id=getattr(request.state, "request_id", None),
        detail={"why": why, "method": request.method, **(detail or {})},
    )
    await db.commit()


# -- admin console ----------------------------------------------------------------------


def require_admin(permission: str) -> Callable[..., Awaitable[Principal]]:
    """Dependency factory: a signed-in administrator holding `permission`. Customer tokens are
    refused by audience, API tokens are never accepted, the role is read from the database."""

    async def dependency(request: Request, db: AsyncSession = Depends(get_session)) -> Principal:
        principal = await _principal(request, db, TokenAudience.admin)
        user = principal.user
        if user.must_change_password:
            raise forbidden("choose a new password before continuing", "password_change_required")
        if not authz.admin_can(user.platform_role, permission):
            await _deny(db, request, principal, "admin_permission", detail={"needed": permission})
            raise forbidden("your administrator role does not allow this")
        return principal

    return dependency
