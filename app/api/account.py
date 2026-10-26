"""Customer-facing accounts: sign up, sign in, sessions, password, API tokens.

Sign-in endpoints are rate limited per client address. The refresh token lives in an httpOnly,
SameSite=Strict cookie scoped to /account, so page scripts can never read it and the browser only
sends it here. The short-lived access token is returned in the body for the app to keep in memory.
"""

import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.security import (
    current_principal,
    forbidden,
    rate_limit_auth,
    request_info,
    require_same_origin,
    session_principal,
    unauthenticated,
)
from app.config import Settings, get_settings
from app.db import get_session
from app.models.enums import TokenAudience
from app.schemas.account import (
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenRead,
    LoginRequest,
    PasswordChangeRequest,
    RegisterRequest,
    SessionRead,
    UserRead,
)
from app.services.access_service import Principal
from app.services.api_token_service import ApiTokenService
from app.services.platform_auth_service import PlatformAuthService, Session

router = APIRouter(prefix="/account", tags=["account"])

APP_COOKIE = "bb_refresh"
APP_COOKIE_PATH = "/account"


def set_refresh_cookie(
    response: Response, name: str, path: str, token: str, max_age: int, settings: Settings
) -> None:
    response.set_cookie(
        name,
        token,
        max_age=max_age,
        path=path,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def clear_refresh_cookie(response: Response, name: str, path: str, settings: Settings) -> None:
    response.delete_cookie(
        name, path=path, httponly=True, secure=settings.cookie_secure, samesite="strict"
    )


def session_body(session: Session) -> SessionRead:
    return SessionRead(
        access_token=session.access_token,
        expires_in=session.expires_in,
        user=UserRead.model_validate(session.user),
    )


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.post(
    "/register",
    response_model=SessionRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_auth)],
)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SessionRead:
    service = PlatformAuthService(db, settings)
    info = request_info(request)
    await service.register(email=body.email, password=body.password, name=body.name, info=info)
    session = await service.login(
        email=body.email, password=body.password, audience=TokenAudience.app, info=info
    )
    set_refresh_cookie(
        response,
        APP_COOKIE,
        APP_COOKIE_PATH,
        session.refresh_token,
        session.refresh_max_age,
        settings,
    )
    _no_store(response)
    return session_body(session)


@router.post("/login", response_model=SessionRead, dependencies=[Depends(rate_limit_auth)])
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SessionRead:
    session = await PlatformAuthService(db, settings).login(
        email=body.email,
        password=body.password,
        audience=TokenAudience.app,
        info=request_info(request),
    )
    set_refresh_cookie(
        response,
        APP_COOKIE,
        APP_COOKIE_PATH,
        session.refresh_token,
        session.refresh_max_age,
        settings,
    )
    _no_store(response)
    return session_body(session)


@router.post(
    "/refresh",
    response_model=SessionRead,
    dependencies=[Depends(rate_limit_auth), Depends(require_same_origin)],
)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SessionRead:
    token = request.cookies.get(APP_COOKIE)
    if not token:
        raise unauthenticated()
    try:
        session = await PlatformAuthService(db, settings).refresh(
            refresh_token=token, audience=TokenAudience.app, info=request_info(request)
        )
    except Exception:
        clear_refresh_cookie(response, APP_COOKIE, APP_COOKIE_PATH, settings)
        raise
    set_refresh_cookie(
        response,
        APP_COOKIE,
        APP_COOKIE_PATH,
        session.refresh_token,
        session.refresh_max_age,
        settings,
    )
    _no_store(response)
    return session_body(session)


@router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_same_origin)]
)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> None:
    token = request.cookies.get(APP_COOKIE)
    if token:
        await PlatformAuthService(db, settings).logout(
            refresh_token=token, info=request_info(request)
        )
    clear_refresh_cookie(response, APP_COOKIE, APP_COOKIE_PATH, settings)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    response: Response,
    principal: Principal = Depends(session_principal),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> None:
    await PlatformAuthService(db, settings).revoke_all_sessions(principal.user)
    await db.commit()
    clear_refresh_cookie(response, APP_COOKIE, APP_COOKIE_PATH, settings)


@router.get("/me", response_model=UserRead)
async def me(principal: Principal = Depends(current_principal)) -> UserRead:
    return UserRead.model_validate(principal.user)


@router.post("/password", response_model=SessionRead, dependencies=[Depends(rate_limit_auth)])
async def change_password(
    body: PasswordChangeRequest,
    request: Request,
    response: Response,
    principal: Principal = Depends(session_principal),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SessionRead:
    session = await PlatformAuthService(db, settings).change_password(
        principal.user,
        current_password=body.current_password,
        new_password=body.new_password,
        audience=TokenAudience.app,
        info=request_info(request),
    )
    set_refresh_cookie(
        response,
        APP_COOKIE,
        APP_COOKIE_PATH,
        session.refresh_token,
        session.refresh_max_age,
        settings,
    )
    _no_store(response)
    return session_body(session)


# -- API tokens: managed with a browser session, never with another API token ---------------


def _active_session(principal: Principal) -> Principal:
    if principal.user.must_change_password:
        raise forbidden("choose a new password before continuing", "password_change_required")
    return principal


@router.get("/tokens", response_model=list[ApiTokenRead])
async def list_tokens(
    principal: Principal = Depends(session_principal), db: AsyncSession = Depends(get_session)
) -> list[ApiTokenRead]:
    _active_session(principal)
    rows = await ApiTokenService(db).list_tokens(principal.user)
    return [ApiTokenRead.model_validate(r) for r in rows]


@router.post("/tokens", response_model=ApiTokenCreated, status_code=status.HTTP_201_CREATED)
async def create_token(
    body: ApiTokenCreate,
    request: Request,
    response: Response,
    principal: Principal = Depends(session_principal),
    db: AsyncSession = Depends(get_session),
) -> ApiTokenCreated:
    _active_session(principal)
    row, raw = await ApiTokenService(db).create(
        principal.user,
        name=body.name,
        description=body.description,
        scopes=body.scopes,
        expires_in_days=body.expires_in_days,
        project_id=body.project_id,
        info=request_info(request),
    )
    _no_store(response)
    return ApiTokenCreated(**ApiTokenRead.model_validate(row).model_dump(), token=raw)


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(session_principal),
    db: AsyncSession = Depends(get_session),
) -> None:
    _active_session(principal)
    await ApiTokenService(db).revoke(principal.user, token_id, request_info(request))
