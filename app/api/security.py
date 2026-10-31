"""The request guard: every builder route passes through here before its handler runs.

`guard` is attached to every router except health and the sign-in endpoints (see app/main.py), so
a route added without thinking about access is still protected. If a route is neither about a
project nor on the short unscoped list in app.core.platform_authz, it is refused (fail closed);
tests/api/test_access_matrix.py walks the OpenAPI schema to make sure none exists.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

import structlog
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core import platform_authz as authz
from app.core import rls
from app.core.ratelimit import SlidingWindowLimiter
from app.db import get_session
from app.exceptions import AppError
from app.models.enums import AuditResult, OrgRole, TokenAudience
from app.models.platform import Organization, OrganizationMember
from app.models.project import Project
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


async def acting_principal(request: Request, db: AsyncSession = Depends(get_session)) -> Principal:
    """Any valid customer-surface credential, including an operator's "view as" token. Only
    `guard` and `org_context` use this: they apply the impersonation rules themselves."""
    return await _principal(request, db, TokenAudience.app)


async def current_principal(
    request: Request, principal: Principal = Depends(acting_principal)
) -> Principal:
    """A customer-surface credential: a session token or an API token. A "view as" token gets
    through only to the few routes listed in IMPERSONATION_OPEN_ROUTES (default deny)."""
    if principal.impersonation is not None:
        route = request.scope.get("route")
        template: str = getattr(route, "path", request.url.path)
        if (request.method.upper(), template) not in authz.IMPERSONATION_OPEN_ROUTES:
            raise forbidden(
                "this isn't available while viewing as another person", "impersonation_blocked"
            )
    return principal


async def _check_impersonation(
    db: AsyncSession,
    request: Request,
    principal: Principal,
    template: str,
    organization_id: object,
) -> None:
    """§4.5: a "view as" token acts inside its one org, may not do what the switch and the
    never-list refuse, and leaves a trail. Called by guard and org_context."""
    info = principal.impersonation
    if info is None:
        return
    if organization_id != info.organization_id:
        raise not_found()
    method = request.method.upper()
    code = authz.impersonation_denial(method, template, writes_allowed=info.writes_allowed())
    detail: dict[str, object] = {
        "method": method,
        "route": template,
        "impersonator_id": str(info.operator_id),
        "session_id": str(info.session_id),
    }
    if code is not None:
        await audit_service.record(
            db,
            action="impersonation.denied",
            result=AuditResult.denied,
            via="impersonation",
            actor_id=principal.user.id,
            actor_email=principal.user.email,
            organization_id=info.organization_id,
            client_ip=client_ip(request),
            request_id=getattr(request.state, "request_id", None),
            detail={**detail, "why": code},
        )
        await db.commit()
        message = (
            "this session is read-only; switch writes on first"
            if code == "impersonation_read_only"
            else "this isn't available while viewing as another person"
        )
        raise forbidden(message, code)
    if method in ("GET", "HEAD", "OPTIONS") or required_read_only_post(method, template):
        await audit_service.record(
            db,
            action="impersonation.request",
            via="impersonation",
            actor_id=principal.user.id,
            actor_email=principal.user.email,
            organization_id=info.organization_id,
            client_ip=client_ip(request),
            request_id=getattr(request.state, "request_id", None),
            detail=detail,
        )
        await db.commit()


def required_read_only_post(method: str, template: str) -> bool:
    return authz.required_scope(method, template) == authz.SCOPE_READ and method not in (
        "GET",
        "HEAD",
        "OPTIONS",
    )


async def session_principal(request: Request, db: AsyncSession = Depends(get_session)) -> Principal:
    """A signed-in browser session only (no API tokens): for managing the account itself."""
    principal = await _principal(request, db, TokenAudience.app)
    if principal.via != "session":
        raise forbidden("this needs a signed-in session, not an API token", "session_required")
    return principal


async def guard(
    request: Request,
    principal: Principal = Depends(acting_principal),
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
        if principal.impersonation is not None:
            await _check_impersonation(
                db, request, principal, template, principal.impersonation.organization_id
            )
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
    # §5: a project belongs to an org, and only that org's members may act on it. Leaving the
    # org removes project memberships too; this is the belt to that pair of braces.
    organization_id = (
        await db.execute(select(Project.organization_id).where(Project.id == project_id))
    ).scalar_one_or_none()
    if (
        organization_id is not None
        and (await db.get(OrganizationMember, (organization_id, user.id))) is None
    ):
        raise not_found()
    if organization_id is not None:
        structlog.contextvars.bind_contextvars(organization_id=str(organization_id))
        await rls.bind(db, organization_id)  # §3.3: the rest of the request sees this org only
        org = await db.get(Organization, organization_id)
        if org is not None and org.deletion_requested_at is not None:
            raise org_deletion_pending(org)
        if org is not None and org.require_mfa and not principal.mfa_satisfied:
            await _deny(db, request, principal, "org_mfa", project_id=project_id)
            raise org_mfa_required(org, principal)
    await _check_impersonation(db, request, principal, template, organization_id)
    needed = authz.required_member_role(method, template)
    if ROLE_LEVEL[role] < ROLE_LEVEL[needed]:
        await _deny(
            db, request, principal, "role", project_id=project_id, detail={"needed": needed.value}
        )
        raise forbidden(f"this needs the project role '{needed.value}'")

    request.state.project_id = project_id
    request.state.organization_id = organization_id
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
            organization_id=organization_id,
            client_ip=client_ip(request),
            request_id=getattr(request.state, "request_id", None),
            detail={
                "method": method,
                "route": template,
                **(
                    {"impersonator_id": str(principal.impersonation.operator_id)}
                    if principal.impersonation is not None
                    else {}
                ),
            },
        )
    return principal


# -- organization routes (§5): /orgs/{slug}/... ------------------------------------------


@dataclass
class OrgContext:
    """The resolved org a /orgs/{slug} request is about, and the caller's role in it."""

    principal: Principal
    summary: Any  # OrgSummary (kept untyped to avoid importing the service at module load)

    @property
    def org(self) -> Any:
        return self.summary.organization

    @property
    def role(self) -> OrgRole:
        return cast(OrgRole, self.summary.role)

    def require(self, needed: OrgRole, owner_emails: list[str]) -> None:
        if not authz.org_role_allows(self.role, needed):
            raise org_forbidden(needed, owner_emails)


def org_deletion_pending(org: Organization) -> AppError:
    """423 Locked: the org is waiting for deletion; only an owner's revoke unlocks it.
    The details name the org, so the UI can link to it without another lookup."""
    when = org.deletion_scheduled_for.isoformat() if org.deletion_scheduled_for else None
    return AppError(
        code="org_deletion_pending",
        message=(
            "this organization is scheduled for deletion and is locked; "
            "an owner can cancel the request to unlock it"
        ),
        status_code=423,
        details=[
            {
                "organization_id": str(org.id),
                "organization_slug": org.slug,
                "organization_name": org.name,
                "deletion_scheduled_for": when,
            }
        ],
    )


def org_mfa_required(org: Organization, principal: Principal) -> AppError:
    """403: the org requires MFA and this session (or this API token's owner) has none.
    `mfa_enabled` tells the UI whether to send the person to set up TOTP or to sign in again."""
    return AppError(
        code="org_mfa_required",
        message=(
            f"{org.name} requires two-factor authentication; "
            "turn it on in your account and sign in again"
        ),
        status_code=403,
        details=[
            {
                "organization_id": str(org.id),
                "organization_slug": org.slug,
                "organization_name": org.name,
                "mfa_enabled": principal.user.mfa_enabled,
            }
        ],
    )


def org_forbidden(needed: OrgRole, owner_emails: list[str]) -> AppError:
    """§8: an admin-only panel answers 403 with the owners' addresses, so the member knows
    whom to ask."""
    return AppError(
        code="org_role_required",
        message=f"this needs the organization role '{needed.value}'",
        status_code=403,
        details=[{"needed_role": needed.value, "owner_emails": owner_emails}],
    )


def require_write_scope(principal: Principal) -> None:
    """Account-level writes (create an org, ...) aren't under `/orgs/{slug}`, so `org_context`
    doesn't see them: an API token needs the `write` scope for them."""
    if principal.via == "api_token" and not authz.scopes_allow(principal.scopes, authz.SCOPE_WRITE):
        raise forbidden(
            f"this API token lacks the '{authz.SCOPE_WRITE}' scope", "insufficient_scope"
        )


async def org_context(
    request: Request,
    principal: Principal = Depends(acting_principal),
    db: AsyncSession = Depends(get_session),
) -> OrgContext:
    """Resolve `{slug}`, check membership (404 otherwise) and the role the route needs."""
    from app.services.organization_service import OrganizationService

    route = request.scope.get("route")
    template: str = getattr(route, "path", request.url.path)
    method = request.method.upper()
    needed = authz.required_org_role(method, template)
    if needed is None:
        log.error("unlisted_org_route_refused", method=method, route=template)
        raise forbidden("this endpoint is not available", "unscoped_route")
    if principal.via == "api_token":
        # A project-pinned token is about one project, never about the org around it.
        if principal.token_project_id is not None:
            raise forbidden("this API token is limited to one project", "insufficient_scope")
        if (method, template) in authz.ORG_ROUTES_SESSION_ONLY:
            raise forbidden(
                "this action needs a signed-in session, not an API token", "session_required"
            )
        needed_scope = authz.SCOPE_READ if method in ("GET", "HEAD") else authz.SCOPE_WRITE
        if not authz.scopes_allow(principal.scopes, needed_scope):
            raise forbidden(
                f"this API token lacks the '{needed_scope}' scope", "insufficient_scope"
            )
    service = OrganizationService(db)
    summary = await service.get_by_slug(principal.user.id, request.path_params["slug"])
    ctx = OrgContext(principal=principal, summary=summary)
    structlog.contextvars.bind_contextvars(organization_id=str(summary.organization.id))
    await _check_impersonation(db, request, principal, template, summary.organization.id)
    await rls.bind(db, summary.organization.id)  # §3.3
    if (
        summary.organization.deletion_requested_at is not None
        and (method, template) not in authz.ORG_ROUTES_OPEN_DURING_DELETION
    ):
        raise org_deletion_pending(summary.organization)
    if (
        summary.organization.require_mfa
        and not principal.mfa_satisfied
        and (method, template) not in authz.ORG_ROUTES_OPEN_WITHOUT_MFA
    ):
        await _deny(db, request, principal, "org_mfa", detail={"route": template})
        raise org_mfa_required(summary.organization, principal)
    if not authz.org_role_allows(summary.role, needed):
        owners = await service.owner_emails(summary.organization.id)
        await audit_service.record(
            db,
            action="access.denied",
            result=AuditResult.denied,
            actor_id=principal.user.id,
            actor_email=principal.user.email,
            via=principal.via,
            organization_id=summary.organization.id,
            client_ip=client_ip(request),
            request_id=getattr(request.state, "request_id", None),
            detail={"why": "org_role", "method": method, "needed": needed.value},
        )
        await db.commit()
        raise org_forbidden(needed, owners)
    request.state.organization_id = summary.organization.id
    return ctx


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

    async def dependency(
        request: Request,
        db: AsyncSession = Depends(get_session),
        settings: Settings = Depends(get_settings),
    ) -> Principal:
        principal = await _principal(request, db, TokenAudience.admin)
        user = principal.user
        # §4.4: staff sign in with a second factor. Login and refresh already insist on it; a
        # token minted without one (older, or from a bug) is refused here too.
        if settings.admin_mfa_required and not principal.mfa_satisfied:
            raise forbidden("sign in again with two-factor authentication", "mfa_required")
        if user.must_change_password:
            raise forbidden("choose a new password before continuing", "password_change_required")
        if not authz.admin_can(user.platform_role, permission):
            await _deny(db, request, principal, "admin_permission", detail={"needed": permission})
            raise forbidden("your administrator role does not allow this")
        return principal

    return dependency
