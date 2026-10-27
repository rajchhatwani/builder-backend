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
from app.exceptions import AppError
from app.models.enums import TokenAudience
from app.schemas.account import (
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenRead,
    DefaultOrganizationUpdate,
    LoginRequest,
    MfaChallengeRead,
    MfaCodeRequest,
    MfaDisableRequest,
    MfaLoginRequest,
    MfaOrgRequirement,
    MfaStatusRead,
    MfaTokenRequest,
    PasswordChangeRequest,
    RecoveryCodesRead,
    RegisterRequest,
    SessionRead,
    SessionWithRecoveryCodesRead,
    TotpSetupRead,
    TotpSetupRequest,
    UserRead,
)
from app.schemas.sso import LoginDiscoverRead, LoginDiscoverRequest
from app.services.access_service import Principal
from app.services.api_token_service import ApiTokenService
from app.services.mfa_service import MfaService
from app.services.platform_auth_service import MfaChallenge, PlatformAuthService, Session

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
    assert isinstance(session, Session)  # a brand-new customer account has no MFA yet
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
    "/login",
    response_model=SessionRead | MfaChallengeRead,
    dependencies=[Depends(rate_limit_auth)],
)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SessionRead | MfaChallengeRead:
    """A session, or `{mfa_required: true, mfa_token, …}` when a second step is needed
    (TOTP on, or platform staff): then call `/account/login/mfa` (or the enrolment pair)."""
    result = await PlatformAuthService(db, settings).login(
        email=body.email,
        password=body.password,
        audience=TokenAudience.app,
        info=request_info(request),
    )
    return login_result(result, response, APP_COOKIE, APP_COOKIE_PATH, settings)


@router.post(
    "/login/discover", response_model=LoginDiscoverRead, dependencies=[Depends(rate_limit_auth)]
)
async def login_discover(
    body: LoginDiscoverRequest,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> LoginDiscoverRead:
    """§4.2 step 1, tenant-first discovery: if the address's domain belongs to an org with
    active SSO, the app sends the browser to `login_url`; otherwise it shows the password
    form. Says nothing about whether an account exists, only about the domain."""
    from app.services.sso_service import SsoService

    service = SsoService(db, settings)
    org = await service.discover(body.email)
    if org is None:
        return LoginDiscoverRead(method="password")
    hint = body.email.strip().lower()
    return LoginDiscoverRead(
        method="sso", login_url=service.login_url(org.slug, hint), organization_name=org.name
    )


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


@router.put("/me/default-organization", response_model=UserRead)
async def set_default_organization(
    body: DefaultOrganizationUpdate,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> UserRead:
    """Choose the org the app opens on (and where unpinned API tokens are counted)."""
    from app.services.organization_service import OrganizationService

    if await OrganizationService(db).member_role(principal.user.id, body.organization_id) is None:
        raise AppError(code="not_found", message="organization not found", status_code=404)
    user = await db.get(type(principal.user), principal.user.id)
    assert user is not None
    user.default_organization_id = body.organization_id
    await db.commit()
    return UserRead.model_validate(user)


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
        methods=" ".join(sorted(principal.auth_methods)) or "pwd",
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


# -- two-factor authentication (§4.4 Phase 1) ------------------------------------------------


def login_result(
    result: Session | MfaChallenge,
    response: Response,
    cookie: str,
    path: str,
    settings: Settings,
) -> SessionRead | MfaChallengeRead:
    """A session (cookie set) or, when a second step is needed, the challenge (no cookie)."""
    _no_store(response)
    if isinstance(result, MfaChallenge):
        return MfaChallengeRead(
            enrollment_required=result.enrollment,
            mfa_token=result.token,
            expires_in=result.expires_in,
            methods=["totp"] if result.enrollment else ["totp", "recovery_code"],
        )
    set_refresh_cookie(
        response, cookie, path, result.refresh_token, result.refresh_max_age, settings
    )
    return session_body(result)


def session_with_codes(session: Session, codes: list[str]) -> SessionWithRecoveryCodesRead:
    return SessionWithRecoveryCodesRead(**session_body(session).model_dump(), recovery_codes=codes)


@router.post("/login/mfa", response_model=SessionRead, dependencies=[Depends(rate_limit_auth)])
async def login_mfa(
    body: MfaLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SessionRead:
    """Second step of a sign-in: a TOTP code or a recovery code for the challenge."""
    session = await MfaService(db, settings).verify_login(
        mfa_token=body.mfa_token,
        code=body.code,
        audience=TokenAudience.app,
        info=request_info(request),
    )
    result = login_result(session, response, APP_COOKIE, APP_COOKIE_PATH, settings)
    assert isinstance(result, SessionRead)
    return result


@router.post(
    "/login/mfa/setup", response_model=TotpSetupRead, dependencies=[Depends(rate_limit_auth)]
)
async def login_mfa_setup(
    body: MfaTokenRequest,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TotpSetupRead:
    """Enrolment challenge only (staff without TOTP): a new secret to scan."""
    setup = await MfaService(db, settings).setup_with_challenge(
        mfa_token=body.mfa_token, audience=TokenAudience.app
    )
    _no_store(response)
    return TotpSetupRead(secret=setup.secret, otpauth_uri=setup.otpauth_uri)


@router.post(
    "/login/mfa/enable",
    response_model=SessionWithRecoveryCodesRead,
    dependencies=[Depends(rate_limit_auth)],
)
async def login_mfa_enable(
    body: MfaLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SessionWithRecoveryCodesRead:
    """Enrolment challenge only: prove the first code, turn TOTP on and sign in."""
    session, codes = await MfaService(db, settings).enable_with_challenge(
        mfa_token=body.mfa_token,
        code=body.code,
        audience=TokenAudience.app,
        info=request_info(request),
    )
    login_result(session, response, APP_COOKIE, APP_COOKIE_PATH, settings)
    return session_with_codes(session, codes)


@router.get("/mfa", response_model=MfaStatusRead)
async def mfa_status(
    principal: Principal = Depends(session_principal),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> MfaStatusRead:
    st = await MfaService(db, settings).status(principal.user)
    return MfaStatusRead(
        totp_enabled=st.totp_enabled,
        enabled_at=st.enabled_at,
        recovery_codes_left=st.recovery_codes_left,
        session_mfa=principal.mfa_satisfied,
        required_for_staff=st.required_for_staff,
        required_by=[
            MfaOrgRequirement(organization_id=o.id, slug=o.slug, name=o.name)
            for o in st.required_by
        ],
        sso_only=st.sso_only,
    )


@router.post(
    "/mfa/totp/setup", response_model=TotpSetupRead, dependencies=[Depends(rate_limit_auth)]
)
async def totp_setup(
    body: TotpSetupRequest,
    response: Response,
    principal: Principal = Depends(session_principal),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TotpSetupRead:
    setup = await MfaService(db, settings).setup(principal.user, password=body.password)
    _no_store(response)
    return TotpSetupRead(secret=setup.secret, otpauth_uri=setup.otpauth_uri)


@router.post(
    "/mfa/totp/enable",
    response_model=SessionWithRecoveryCodesRead,
    dependencies=[Depends(rate_limit_auth)],
)
async def totp_enable(
    body: MfaCodeRequest,
    request: Request,
    response: Response,
    principal: Principal = Depends(session_principal),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SessionWithRecoveryCodesRead:
    """Turn TOTP on. Answers a fresh session that counts as MFA'd and the recovery codes."""
    session, codes = await MfaService(db, settings).enable(
        principal.user, code=body.code, info=request_info(request)
    )
    login_result(session, response, APP_COOKIE, APP_COOKIE_PATH, settings)
    return session_with_codes(session, codes)


@router.post(
    "/mfa/totp/disable",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit_auth)],
)
async def totp_disable(
    body: MfaDisableRequest,
    request: Request,
    principal: Principal = Depends(session_principal),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> None:
    await MfaService(db, settings).disable(
        principal.user, password=body.password, code=body.code, info=request_info(request)
    )


@router.post(
    "/mfa/recovery-codes",
    response_model=RecoveryCodesRead,
    dependencies=[Depends(rate_limit_auth)],
)
async def regenerate_recovery_codes(
    body: MfaCodeRequest,
    request: Request,
    response: Response,
    principal: Principal = Depends(session_principal),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RecoveryCodesRead:
    codes = await MfaService(db, settings).regenerate_recovery_codes(
        principal.user, code=body.code, info=request_info(request)
    )
    _no_store(response)
    return RecoveryCodesRead(recovery_codes=codes)


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
