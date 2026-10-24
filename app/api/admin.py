"""Admin console API. A separate surface from the customer app:

- its own sign-in (`/admin/login`) that only accepts people with a platform role,
- tokens with a different audience, so a customer token is refused here and an admin token is
  refused on customer routes,
- its own refresh cookie (12 hours by default) scoped to /admin,
- permissions read from the database on every request (support = read-only, admin = full).
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.account import clear_refresh_cookie, session_body, set_refresh_cookie
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
from app.models.enums import AccountStatus, AuditResult, PlatformRole, TokenAudience
from app.schemas.account import (
    AdminProjectRead,
    AdminStats,
    AdminUserCreate,
    AdminUserCreated,
    AdminUserRead,
    AdminUserUpdate,
    AuditRead,
    LoginRequest,
    PlatformSettingsRead,
    SessionRead,
    UserRead,
)
from app.schemas.common import Page
from app.services import audit_service
from app.services.access_service import Principal
from app.services.admin_service import AdminService
from app.services.platform_auth_service import PlatformAuthService

router = APIRouter(prefix="/admin", tags=["admin"])

NEEDS_AUDIT_READ = Depends(require_admin("audit:read"))
NEEDS_PROJECTS_READ = Depends(require_admin("projects:read"))
NEEDS_SETTINGS_READ = Depends(require_admin("settings:read"))
NEEDS_STATS_READ = Depends(require_admin("stats:read"))
NEEDS_USERS_READ = Depends(require_admin("users:read"))
NEEDS_USERS_WRITE = Depends(require_admin("users:write"))
QUERY_TEXT = Query(default=None, max_length=100)
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


@router.post("/login", response_model=SessionRead, dependencies=[Depends(rate_limit_auth)])
async def admin_login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SessionRead:
    session = await PlatformAuthService(db, settings).login(
        email=body.email,
        password=body.password,
        audience=TokenAudience.admin,
        info=request_info(request),
    )
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
    since: datetime | None = None,
    result: AuditResult | None = None,
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
        since=since,
        result=result,
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
