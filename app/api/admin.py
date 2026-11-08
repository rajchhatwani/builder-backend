"""Admin console API. A separate surface from the customer app:

- its own sign-in (`/admin/login`) that only accepts people with a platform role,
- tokens with a different audience, so a customer token is refused here and an admin token is
  refused on customer routes,
- its own refresh cookie (12 hours by default) scoped to /admin,
- permissions read from the database on every request (support = read-only, admin = full).
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.account import (
    clear_refresh_cookie,
    login_result,
    session_body,
    session_with_codes,
    set_refresh_cookie,
)
from app.api.deps import Pagination, pagination
from app.api.security import (
    rate_limit_auth,
    request_info,
    require_admin,
    require_same_origin,
    unauthenticated,
)
from app.config import Settings, get_settings
from app.db import get_session
from app.exceptions import AppError
from app.models.enums import (
    AccountStatus,
    AuditResult,
    PlatformRole,
    SubscriptionStatus,
    TokenAudience,
)
from app.models.platform import PlatformUser
from app.schemas.account import (
    AdminInsights,
    AdminOrgDeletionUpdate,
    AdminOrgMemberRead,
    AdminOrgPlanChange,
    AdminOrgProjectRead,
    AdminOrgRead,
    AdminOrgSeatOverride,
    AdminProjectRead,
    AdminReason,
    AdminStats,
    AdminSubscriptionRead,
    AdminUserCreate,
    AdminUserCreated,
    AdminUserRead,
    AdminUserUpdate,
    ApiTokenRead,
    AuditRead,
    ImpersonationDigestRead,
    ImpersonationRequest,
    ImpersonationSessionRead,
    ImpersonationStarted,
    LoginRequest,
    MfaChallengeRead,
    MfaLoginRequest,
    MfaTokenRequest,
    PlanWrite,
    PlatformSettingsRead,
    SessionRead,
    SessionWithRecoveryCodesRead,
    TotpSetupRead,
    UserRead,
)
from app.schemas.common import Page
from app.schemas.organization import PlanRead
from app.schemas.sso import SsoCheckRead
from app.services import audit_service, impersonation_digest
from app.services.access_service import Principal
from app.services.admin_service import AdminService
from app.services.impersonation_service import ImpersonationService
from app.services.mfa_service import MfaService
from app.services.platform_auth_service import PlatformAuthService

router = APIRouter(prefix="/admin", tags=["admin"])

NEEDS_AUDIT_READ = Depends(require_admin("audit:read"))
NEEDS_PROJECTS_READ = Depends(require_admin("projects:read"))
NEEDS_SETTINGS_READ = Depends(require_admin("settings:read"))
NEEDS_STATS_READ = Depends(require_admin("stats:read"))
NEEDS_USERS_READ = Depends(require_admin("users:read"))
NEEDS_USERS_WRITE = Depends(require_admin("users:write"))
NEEDS_SSO_CHECK = Depends(require_admin("sso:check"))
QUERY_TEXT = Query(default=None, max_length=100)
STATUS_FILTER = Query(default=None, alias="status")
QUERY_ACTION = Query(default=None, max_length=60)
QUERY_STATUS = Query(default=None, alias="status")

ADMIN_COOKIE = "bb_admin_refresh"
ADMIN_COOKIE_PATH = "/admin"


def _user_read(user: object, project_count: int = 0) -> AdminUserRead:
    return AdminUserRead.model_validate(
        {
            **UserRead.model_validate(user).model_dump(),
            "failed_logins": user.failed_logins,  # type: ignore[attr-defined]
            "locked_until": user.locked_until,  # type: ignore[attr-defined]
            "project_count": project_count,
        }
    )


# -- session ---------------------------------------------------------------------------


@router.post(
    "/login",
    response_model=SessionRead | MfaChallengeRead,
    dependencies=[Depends(rate_limit_auth)],
)
async def admin_login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SessionRead | MfaChallengeRead:
    """§4.4: staff always need TOTP, so a correct password answers an MFA challenge
    (`enrollment_required` when the account has no TOTP yet), never a session by itself
    (unless `BUILDER_ADMIN_MFA_REQUIRED=false`, local development only)."""
    result = await PlatformAuthService(db, settings).login(
        email=body.email,
        password=body.password,
        audience=TokenAudience.admin,
        info=request_info(request),
    )
    return login_result(result, response, ADMIN_COOKIE, ADMIN_COOKIE_PATH, settings)


@router.post("/login/mfa", response_model=SessionRead, dependencies=[Depends(rate_limit_auth)])
async def admin_login_mfa(
    body: MfaLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SessionRead:
    session = await MfaService(db, settings).verify_login(
        mfa_token=body.mfa_token,
        code=body.code,
        audience=TokenAudience.admin,
        info=request_info(request),
    )
    result = login_result(session, response, ADMIN_COOKIE, ADMIN_COOKIE_PATH, settings)
    assert isinstance(result, SessionRead)
    return result


@router.post(
    "/login/mfa/setup", response_model=TotpSetupRead, dependencies=[Depends(rate_limit_auth)]
)
async def admin_login_mfa_setup(
    body: MfaTokenRequest,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TotpSetupRead:
    setup = await MfaService(db, settings).setup_with_challenge(
        mfa_token=body.mfa_token, audience=TokenAudience.admin
    )
    response.headers["Cache-Control"] = "no-store"
    return TotpSetupRead(secret=setup.secret, otpauth_uri=setup.otpauth_uri)


@router.post(
    "/login/mfa/enable",
    response_model=SessionWithRecoveryCodesRead,
    dependencies=[Depends(rate_limit_auth)],
)
async def admin_login_mfa_enable(
    body: MfaLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SessionWithRecoveryCodesRead:
    session, codes = await MfaService(db, settings).enable_with_challenge(
        mfa_token=body.mfa_token,
        code=body.code,
        audience=TokenAudience.admin,
        info=request_info(request),
    )
    login_result(session, response, ADMIN_COOKIE, ADMIN_COOKIE_PATH, settings)
    return session_with_codes(session, codes)


@router.post(
    "/refresh",
    response_model=SessionRead,
    dependencies=[Depends(rate_limit_auth), Depends(require_same_origin)],
)
async def admin_refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SessionRead:
    token = request.cookies.get(ADMIN_COOKIE)
    if not token:
        raise unauthenticated()
    try:
        session = await PlatformAuthService(db, settings).refresh(
            refresh_token=token, audience=TokenAudience.admin, info=request_info(request)
        )
    except Exception:
        clear_refresh_cookie(response, ADMIN_COOKIE, ADMIN_COOKIE_PATH, settings)
        raise
    set_refresh_cookie(
        response,
        ADMIN_COOKIE,
        ADMIN_COOKIE_PATH,
        session.refresh_token,
        session.refresh_max_age,
        settings,
    )
    response.headers["Cache-Control"] = "no-store"
    return session_body(session)


@router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_same_origin)]
)
async def admin_logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> None:
    token = request.cookies.get(ADMIN_COOKIE)
    if token:
        await PlatformAuthService(db, settings).logout(
            refresh_token=token, info=request_info(request)
        )
    clear_refresh_cookie(response, ADMIN_COOKIE, ADMIN_COOKIE_PATH, settings)


@router.get("/me", response_model=UserRead)
async def admin_me(principal: Principal = NEEDS_STATS_READ) -> UserRead:
    return UserRead.model_validate(principal.user)


# -- users -----------------------------------------------------------------------------


@router.get("/users", response_model=Page[AdminUserRead])
async def list_users(
    page: Pagination = Depends(pagination),
    q: str | None = QUERY_TEXT,
    status_filter: AccountStatus | None = QUERY_STATUS,
    role: PlatformRole | None = None,
    _: Principal = NEEDS_USERS_READ,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Page[AdminUserRead]:
    rows, total = await AdminService(db, settings).list_users(
        limit=page.limit, offset=page.offset, query=q, status=status_filter, role=role
    )
    return Page[AdminUserRead](
        items=[_user_read(u, n) for u, n in rows], total=total, limit=page.limit, offset=page.offset
    )


@router.post("/users", response_model=AdminUserCreated, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: AdminUserCreate,
    request: Request,
    response: Response,
    principal: Principal = NEEDS_USERS_WRITE,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AdminUserCreated:
    user, generated = await AdminService(db, settings).create_user(
        principal,
        email=body.email,
        name=body.name,
        role=body.platform_role,
        password=body.password,
        info=request_info(request),
    )
    response.headers["Cache-Control"] = "no-store"
    return AdminUserCreated(user=_user_read(user), temporary_password=generated)


@router.get("/users/{user_id}", response_model=AdminUserRead)
async def get_user(
    user_id: uuid.UUID,
    _: Principal = NEEDS_USERS_READ,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AdminUserRead:
    user, count = await AdminService(db, settings).get_user(user_id)
    return _user_read(user, count)


@router.patch("/users/{user_id}", response_model=AdminUserRead)
async def update_user(
    user_id: uuid.UUID,
    body: AdminUserUpdate,
    request: Request,
    principal: Principal = NEEDS_USERS_WRITE,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AdminUserRead:
    service = AdminService(db, settings)
    await service.update_user(
        principal,
        user_id,
        name=body.name,
        status=body.status,
        role=body.platform_role,
        info=request_info(request),
    )
    user, count = await service.get_user(user_id)
    return _user_read(user, count)


@router.post("/users/{user_id}/revoke-sessions", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_sessions(
    user_id: uuid.UUID,
    request: Request,
    principal: Principal = NEEDS_USERS_WRITE,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> None:
    await AdminService(db, settings).revoke_sessions(principal, user_id, request_info(request))


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: uuid.UUID,
    request: Request,
    response: Response,
    principal: Principal = NEEDS_USERS_WRITE,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    temporary = await AdminService(db, settings).reset_password(
        principal, user_id, request_info(request)
    )
    response.headers["Cache-Control"] = "no-store"
    return {"temporary_password": temporary}


@router.post("/users/{user_id}/reset-mfa", response_model=AdminUserRead)
async def reset_mfa(
    user_id: uuid.UUID,
    body: AdminReason,
    request: Request,
    principal: Principal = NEEDS_USERS_WRITE,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AdminUserRead:
    """Clear a person's TOTP and recovery codes (lost authenticator) and sign them out
    everywhere. Needs a reason; audited as `admin.user_mfa_reset`."""
    user = await db.get(PlatformUser, user_id)
    if user is None:
        raise AppError(code="not_found", message="user not found", status_code=404)
    if user.id == principal.user.id:
        raise AppError(
            code="cannot_reset_own_mfa",
            message="ask another administrator to reset your two-factor authentication",
            status_code=409,
        )
    user = await MfaService(db, settings).reset_by_operator(
        user, actor=principal.user, reason=body.reason, info=request_info(request)
    )
    return _user_read(user)


# -- projects (metadata only), audit, stats, settings ---------------------------------------


@router.get("/projects", response_model=Page[AdminProjectRead])
async def list_projects(
    page: Pagination = Depends(pagination),
    q: str | None = QUERY_TEXT,
    _: Principal = NEEDS_PROJECTS_READ,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Page[AdminProjectRead]:
    rows, total = await AdminService(db, settings).list_projects(
        limit=page.limit, offset=page.offset, query=q
    )
    return Page[AdminProjectRead](
        items=[
            AdminProjectRead(
                id=p.id,
                name=p.name,
                slug=p.slug,
                created_at=p.created_at,
                owner_emails=owners,
                entity_count=entities,
            )
            for p, owners, entities in rows
        ],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/audit", response_model=Page[AuditRead])
async def audit(
    page: Pagination = Depends(pagination),
    actor_id: uuid.UUID | None = None,
    action: str | None = QUERY_ACTION,
    project_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    since: datetime | None = None,
    result: AuditResult | None = None,
    via: str | None = Query(default=None, max_length=20),
    _: Principal = NEEDS_AUDIT_READ,
    db: AsyncSession = Depends(get_session),
) -> Page[AuditRead]:
    rows, total = await audit_service.search(
        db,
        limit=page.limit,
        offset=page.offset,
        actor_id=actor_id,
        action=action,
        project_id=project_id,
        organization_id=organization_id,
        since=since,
        result=result,
        via=via,
    )
    return Page[AuditRead](
        items=[AuditRead.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/stats", response_model=AdminStats)
async def stats(
    _: Principal = NEEDS_STATS_READ,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AdminStats:
    return await AdminService(db, settings).stats()


@router.get("/settings", response_model=PlatformSettingsRead)
async def platform_settings(
    _: Principal = NEEDS_SETTINGS_READ,
    settings: Settings = Depends(get_settings),
) -> PlatformSettingsRead:
    """Read-only on purpose: settings are configuration as code (environment variables)."""
    return PlatformSettingsRead(
        environment=settings.environment,
        signup_mode=settings.signup_mode,
        access_token_minutes=settings.access_token_minutes,
        refresh_token_days=settings.refresh_token_days,
        admin_refresh_token_hours=settings.admin_refresh_token_hours,
        login_max_failures=settings.login_max_failures,
        lockout_minutes=settings.lockout_minutes,
        trust_proxy_headers=settings.trust_proxy_headers,
        docs_enabled=settings.docs_enabled,
        cors_origins=settings.cors_origins,
    )


# -- user token management (admin) -----------------------------------------------------


@router.get("/users/{user_id}/tokens", response_model=list[ApiTokenRead])
async def admin_list_user_tokens(
    user_id: uuid.UUID,
    _: Principal = NEEDS_USERS_READ,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[ApiTokenRead]:
    """List all tokens for a specific user. Includes revoked tokens for audit visibility."""
    # Verify user exists first
    await AdminService(db, settings).get_user(user_id)
    from app.services.api_token_service import ApiTokenService

    rows = await ApiTokenService(db).list_for_user_admin(user_id)
    return [ApiTokenRead.model_validate(r) for r in rows]


@router.delete("/users/{user_id}/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_revoke_user_token(
    user_id: uuid.UUID,
    token_id: uuid.UUID,
    request: Request,
    principal: Principal = NEEDS_USERS_WRITE,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> None:
    """Platform admin revokes any token belonging to a user."""
    await AdminService(db, settings).get_user(user_id)
    from app.services.api_token_service import ApiTokenService

    await ApiTokenService(db).revoke_admin(principal.user, user_id, token_id, request_info(request))


# -- organizations tab -----------------------------------------------------------------


def _org_row(
    org: object,
    member_count: int,
    project_count: int,
    sub: object,
    extras: tuple[int, datetime | None] = (0, None),
    sso: dict[str, object] | None = None,
) -> AdminOrgRead:
    return AdminOrgRead(
        **(sso or {}),  # type: ignore[arg-type]
        require_mfa=getattr(org, "require_mfa", False),
        session_ttl_hours=getattr(org, "session_ttl_hours", None),
        allow_impersonation=getattr(org, "allow_impersonation", True),
        stripe_customer_id=getattr(sub, "stripe_customer_id", None),
        stripe_subscription_id=getattr(sub, "stripe_subscription_id", None),
        current_period_end=getattr(sub, "current_period_end", None),
        trial_ends_at=getattr(sub, "trial_ends_at", None),
        mrr_cents=extras[0],
        last_activity_at=extras[1],
        deletion_requested_at=getattr(org, "deletion_requested_at", None),
        deletion_scheduled_for=getattr(org, "deletion_scheduled_for", None),
        id=org.id,  # type: ignore[attr-defined]
        name=org.name,  # type: ignore[attr-defined]
        slug=org.slug,  # type: ignore[attr-defined]
        kind=org.kind.value,  # type: ignore[attr-defined]
        created_at=org.created_at,  # type: ignore[attr-defined]
        deleted_at=org.deleted_at,  # type: ignore[attr-defined]
        member_count=member_count,
        project_count=project_count,
        plan_id=sub.plan_id if sub is not None else "",  # type: ignore[attr-defined]
        status=sub.status.value if sub is not None else "",  # type: ignore[attr-defined]
        seat_override=sub.seat_override if sub is not None else None,  # type: ignore[attr-defined]
        project_override=(
            sub.project_override if sub is not None else None  # type: ignore[attr-defined]
        ),
    )


@router.get("/organizations", response_model=Page[AdminOrgRead])
async def list_organizations(
    page: Pagination = Depends(pagination),
    q: str | None = QUERY_TEXT,
    _: Principal = NEEDS_PROJECTS_READ,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Page[AdminOrgRead]:
    service = AdminService(db, settings)
    rows, total = await service.list_organizations(limit=page.limit, offset=page.offset, query=q)
    extras = await service.org_extras(rows)
    sso = await service.org_sso([o.id for o, *_ in rows])
    scim = await service.org_scim([o.id for o, *_ in rows])
    for oid, extra in scim.items():
        sso.setdefault(oid, {}).update(extra)
    return Page[AdminOrgRead](
        items=[
            _org_row(o, m, p, s, extras.get(o.id, (0, None)), sso.get(o.id)) for o, m, p, s in rows
        ],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


async def _one_org(service: AdminService, org_id: uuid.UUID) -> AdminOrgRead:
    row = await service.get_organization(org_id)
    extras = await service.org_extras([row])
    sso = await service.org_sso([org_id])
    sso.setdefault(org_id, {}).update((await service.org_scim([org_id])).get(org_id, {}))
    return _org_row(*row, extras.get(org_id, (0, None)), sso.get(org_id))


@router.get("/organizations/{org_id}", response_model=AdminOrgRead)
async def get_organization(
    org_id: uuid.UUID,
    _: Principal = NEEDS_PROJECTS_READ,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AdminOrgRead:
    return await _one_org(AdminService(db, settings), org_id)


@router.patch("/organizations/{org_id}/overrides", response_model=AdminOrgRead)
async def set_org_overrides(
    org_id: uuid.UUID,
    body: AdminOrgSeatOverride,
    request: Request,
    principal: Principal = NEEDS_USERS_WRITE,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AdminOrgRead:
    service = AdminService(db, settings)
    await service.set_org_overrides(
        principal,
        org_id,
        seat_override=body.seat_override,
        project_override=body.project_override,
        reason=body.reason,
        info=request_info(request),
    )
    return await _one_org(service, org_id)


@router.patch("/organizations/{org_id}/plan", response_model=AdminOrgRead)
async def set_org_plan(
    org_id: uuid.UUID,
    body: AdminOrgPlanChange,
    request: Request,
    principal: Principal = NEEDS_USERS_WRITE,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AdminOrgRead:
    service = AdminService(db, settings)
    await service.set_org_plan(
        principal, org_id, plan_id=body.plan_id, reason=body.reason, info=request_info(request)
    )
    return await _one_org(service, org_id)


@router.patch("/organizations/{org_id}/deletion", response_model=AdminOrgRead)
async def reschedule_org_deletion(
    org_id: uuid.UUID,
    body: AdminOrgDeletionUpdate,
    principal: Principal = NEEDS_USERS_WRITE,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AdminOrgRead:
    from app.services.organization_service import OrganizationService

    org = await OrganizationService(db).reschedule_deletion(org_id, grace_days=body.grace_days)
    await audit_service.record(
        db,
        action="admin.org_deletion_rescheduled",
        actor_id=principal.user.id,
        actor_email=principal.user.email,
        organization_id=org_id,
        target_type="organization",
        target_id=org_id,
        detail={
            "scheduled_for": org.deletion_scheduled_for.isoformat()
            if org.deletion_scheduled_for
            else None,
            "reason": body.reason[:200],
        },
    )
    await db.commit()
    return await _one_org(AdminService(db, settings), org_id)


@router.post("/organizations/{org_id}/deletion/execute", response_model=AdminOrgRead)
async def execute_org_deletion(
    org_id: uuid.UUID,
    body: AdminReason,
    principal: Principal = NEEDS_USERS_WRITE,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AdminOrgRead:
    """Accept a pending deletion request now, without waiting for the grace period."""
    from app.models.platform import Organization
    from app.services import org_deletion_service

    org = await db.get(Organization, org_id)
    if org is None or org.deleted_at is not None:
        raise AppError(code="not_found", message="organization not found", status_code=404)
    if org.deletion_requested_at is None:
        raise AppError(
            code="no_deletion_request",
            message="the organization's owner hasn't requested deletion",
            status_code=409,
        )
    await org_deletion_service.execute(
        db,
        org_id,
        actor_id=principal.user.id,
        actor_email=principal.user.email,
        reason=f"accepted early by operator: {body.reason}",
    )
    return await _one_org(AdminService(db, settings), org_id)


@router.post("/organizations/{org_id}/sso/check", response_model=SsoCheckRead)
async def check_org_sso(
    org_id: uuid.UUID,
    request: Request,
    principal: Principal = NEEDS_SSO_CHECK,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SsoCheckRead:
    """§12.D.5 operator test button: checks the org's SSO configuration (plan, verified
    domain, IdP certificate expiry, OIDC discovery + JWKS) without signing anyone in."""
    from app.api.sso import check_read
    from app.models.platform import Organization
    from app.services.sso_service import SsoService

    org = await db.get(Organization, org_id)
    if org is None or org.deleted_at is not None:
        raise AppError(code="not_found", message="organization not found", status_code=404)
    result = await SsoService(db, settings).check(org)
    info = request_info(request)
    await audit_service.record(
        db,
        action="admin.sso_checked",
        actor_id=principal.user.id,
        actor_email=principal.user.email,
        via="session",
        organization_id=org.id,
        target_type="organization",
        target_id=org.id,
        client_ip=info.client_ip,
        request_id=info.request_id,
        detail={"ok": result.ok},
    )
    await db.commit()
    return check_read(result)


@router.post("/sso/domains/{domain}/release", response_model=AdminOrgRead)
async def release_sso_domain(
    domain: str,
    body: AdminReason,
    request: Request,
    principal: Principal = NEEDS_USERS_WRITE,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AdminOrgRead:
    """Frees a verified (or pending) SSO domain claim so another org can verify it. If it was
    the holder's last verified domain its SSO is switched off. Platform admins only; needs a
    reason; audited as `admin.sso_domain_released`. Returns the org that held the claim."""
    from app.services.sso_service import SsoService

    org = await SsoService(db, settings).operator_release_domain(
        domain, principal.user, body.reason, request_info(request)
    )
    return await _one_org(AdminService(db, settings), org.id)


@router.post("/organizations/{org_id}/scim/rotate", response_model=AdminOrgRead)
async def rotate_org_scim_token(
    org_id: uuid.UUID,
    body: AdminReason,
    request: Request,
    principal: Principal = NEEDS_USERS_WRITE,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AdminOrgRead:
    """§12.E.4 bearer rotation: replaces the org's SCIM token with one nobody sees (§7.1) and
    switches the directory off, until an org admin issues a new token. For a leaked token.
    Platform admins only; needs a reason; audited as `admin.scim_token_rotated`."""
    from app.models.platform import Organization
    from app.services.scim_service import ScimService

    org = await db.get(Organization, org_id)
    if org is None or org.deleted_at is not None:
        raise AppError(code="not_found", message="organization not found", status_code=404)
    await ScimService(db, settings).operator_rotate(
        org, principal.user, body.reason, request_info(request)
    )
    return await _one_org(AdminService(db, settings), org_id)


@router.get("/organizations/{org_id}/members", response_model=list[AdminOrgMemberRead])
async def org_members(
    org_id: uuid.UUID,
    _: Principal = NEEDS_USERS_READ,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[AdminOrgMemberRead]:
    rows = await AdminService(db, settings).org_members(org_id)
    return [
        AdminOrgMemberRead(
            user_id=u.id,
            email=u.email,
            name=u.name,
            role=m.role.value,
            joined_at=m.joined_at,
            status=u.status,
            last_login_at=u.last_login_at,
            mfa_enabled=u.mfa_enabled,
        )
        for m, u in rows
    ]


@router.get("/organizations/{org_id}/projects", response_model=list[AdminOrgProjectRead])
async def org_projects(
    org_id: uuid.UUID,
    _: Principal = NEEDS_PROJECTS_READ,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[AdminOrgProjectRead]:
    rows = await AdminService(db, settings).org_projects(org_id)
    return [
        AdminOrgProjectRead(
            id=p.id,
            name=p.name,
            slug=p.slug,
            created_at=p.created_at,
            updated_at=p.updated_at,
            entity_count=n,
        )
        for p, n in rows
    ]


# -- impersonation (§4.5, §7.1): platform admins only, with their own permission ----------------

NEEDS_IMPERSONATE = Depends(require_admin("impersonate:write"))


@router.post(
    "/organizations/{org_id}/members/{user_id}/impersonate",
    response_model=ImpersonationStarted,
    status_code=status.HTTP_201_CREATED,
)
async def impersonate(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    body: ImpersonationRequest,
    request: Request,
    principal: Principal = NEEDS_IMPERSONATE,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ImpersonationStarted:
    """Mint a ten-minute "view as" token for one member of an org that allows it. Read-only
    until the viewer switches writes on; every request is audited; staff are never viewed."""
    started = await ImpersonationService(db, settings).start(
        principal, org_id, user_id, body.reason, request_info(request)
    )
    return ImpersonationStarted(
        session_id=started.session.id,
        access_token=started.access_token,
        expires_in=started.expires_in,
        expires_at=started.session.expires_at,
        user_email=started.user.email,
        organization_id=started.organization.id,
        organization_slug=started.organization.slug,
    )


@router.get("/impersonation/sessions", response_model=Page[ImpersonationSessionRead])
async def impersonation_sessions(
    page: Pagination = Depends(pagination),
    organization_id: uuid.UUID | None = None,
    _: Principal = NEEDS_IMPERSONATE,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Page[ImpersonationSessionRead]:
    rows, total = await ImpersonationService(db, settings).sessions(
        limit=page.limit, offset=page.offset, organization_id=organization_id
    )
    now = datetime.now(UTC)
    items = [
        ImpersonationSessionRead(
            id=r.id,
            operator_email=op,
            user_email=target,
            organization_id=r.organization_id,
            organization_slug=slug,
            reason=r.reason,
            created_at=r.created_at,
            expires_at=r.expires_at,
            ended_at=r.ended_at,
            writes_until=r.writes_until,
            active=r.ended_at is None and r.expires_at > now,
        )
        for r, op, target, slug in rows
    ]
    return Page[ImpersonationSessionRead](
        items=items, total=total, limit=page.limit, offset=page.offset
    )


@router.get("/impersonation/digest", response_model=ImpersonationDigestRead)
async def impersonation_digest_preview(
    hours: int = Query(default=24, ge=1, le=168),
    _: Principal = NEEDS_IMPERSONATE,
    db: AsyncSession = Depends(get_session),
) -> ImpersonationDigestRead:
    """What the daily digest would say for the last `hours` hours (nothing is sent)."""
    until = datetime.now(UTC)
    d = await impersonation_digest.build(db, until - timedelta(hours=hours), until)
    return ImpersonationDigestRead(
        since=d.since, until=d.until, sessions=d.sessions, refused=d.refused, text=d.text
    )


@router.post("/impersonation/sessions/{session_id}/end", status_code=status.HTTP_204_NO_CONTENT)
async def end_impersonation(
    session_id: uuid.UUID,
    request: Request,
    principal: Principal = NEEDS_IMPERSONATE,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    await ImpersonationService(db, settings).end(
        session_id, by=principal, why="ended_by_operator", info=request_info(request)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- billing tab and insights (§7) -------------------------------------------------------


@router.get("/subscriptions", response_model=Page[AdminSubscriptionRead])
async def list_subscriptions(
    page: Pagination = Depends(pagination),
    status_filter: SubscriptionStatus | None = STATUS_FILTER,
    q: str | None = QUERY_TEXT,
    _: Principal = NEEDS_PROJECTS_READ,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Page[AdminSubscriptionRead]:
    rows, total = await AdminService(db, settings).list_subscriptions(
        limit=page.limit, offset=page.offset, status=status_filter, query=q
    )
    return Page[AdminSubscriptionRead](
        items=[
            AdminSubscriptionRead(
                organization_id=org.id,
                organization_slug=org.slug,
                organization_name=org.name,
                plan_id=sub.plan_id,
                status=sub.status.value,
                current_period_end=sub.current_period_end,
                trial_ends_at=sub.trial_ends_at,
                stripe_customer_id=sub.stripe_customer_id,
                stripe_subscription_id=sub.stripe_subscription_id,
                seat_override=sub.seat_override,
                updated_at=sub.updated_at,
            )
            for sub, org in rows
        ],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/insights", response_model=AdminInsights)
async def insights(
    _: Principal = NEEDS_STATS_READ,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AdminInsights:
    return AdminInsights.model_validate(await AdminService(db, settings).insights())


@router.post("/billing/reconcile")
async def run_billing_reconcile(
    _: Principal = NEEDS_USERS_WRITE,
    db: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    """Re-read every Stripe subscription and expire due trials (also runs from cron)."""
    from app.services.billing_reconcile import reconcile

    return (await reconcile(db)).as_dict()


# -- plans tab -------------------------------------------------------------------------


@router.get("/plans", response_model=list[PlanRead])
async def list_plans(
    _: Principal = NEEDS_SETTINGS_READ,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> list[PlanRead]:
    rows = await AdminService(db, settings).list_plans()
    return [PlanRead.model_validate(r) for r in rows]


@router.put("/plans/{plan_id}", response_model=PlanRead)
async def upsert_plan(
    plan_id: str,
    body: PlanWrite,
    request: Request,
    principal: Principal = NEEDS_USERS_WRITE,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> PlanRead:
    plan = await AdminService(db, settings).upsert_plan(
        principal, plan_id, body.model_dump(), request_info(request)
    )
    return PlanRead.model_validate(plan)
