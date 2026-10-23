"""HTTP routes for authentication (generated)."""
import typing as _t

import fastapi as _fa

from app.auth import config
from app.auth.delivery import Mailer, SmsSender, get_mailer, get_sms_sender
from app.auth.deps import CurrentUser
from app.auth.ratelimit import RateLimiter
from app.auth.schemas import (
    Accepted,
    ChangePasswordRequest,
    EmailRequest,
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    TokenRequest,
    UserRead,
)
from app.auth.service import AuthService
from app.db import SessionDep

router = _fa.APIRouter(prefix="/auth", tags=["auth"])

MailerDep = _t.Annotated[Mailer, _fa.Depends(get_mailer)]
SmsDep = _t.Annotated[SmsSender, _fa.Depends(get_sms_sender)]

_login_limit = RateLimiter("login", config.LOGIN_RATE_LIMIT)
_register_limit = RateLimiter("register", config.REGISTER_RATE_LIMIT)
_reset_limit = RateLimiter("reset", config.RESET_RATE_LIMIT)


async def _tokens(service: AuthService, user: _t.Any) -> TokenPair:
    access, refresh, expires_in = await service.issue_tokens(user)
    return TokenPair(access_token=access, refresh_token=refresh, expires_in=expires_in)


@router.post(
    "/register",
    response_model=UserRead,
    status_code=201,
    dependencies=[_fa.Depends(_register_limit)],
)
async def register(body: RegisterRequest, session: SessionDep, mailer: MailerDep) -> UserRead:
    user = await AuthService(session).register(body.model_dump(), mailer)
    return UserRead.model_validate(user)


@router.post("/login", response_model=TokenPair, dependencies=[_fa.Depends(_login_limit)])
async def login(body: LoginRequest, session: SessionDep) -> TokenPair:
    service = AuthService(session)
    user = await service.authenticate(body.email, body.password)
    return await _tokens(service, user)


@router.post("/refresh", response_model=TokenPair, dependencies=[_fa.Depends(_login_limit)])
async def refresh(body: RefreshRequest, session: SessionDep) -> TokenPair:
    access, new_refresh, expires_in = await AuthService(session).refresh(body.refresh_token)
    return TokenPair(access_token=access, refresh_token=new_refresh, expires_in=expires_in)


@router.post("/logout", status_code=204)
async def logout(body: RefreshRequest, session: SessionDep) -> None:
    """Revokes the refresh token and every token rotated from it."""
    await AuthService(session).logout(body.refresh_token)


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.delete("/me", status_code=204)
async def delete_me(user: CurrentUser, session: SessionDep) -> None:
    """Disables the account (soft delete): it can no longer sign in, but the row is kept."""
    await AuthService(session).delete_account(user)


@router.post("/change-password", status_code=204)
async def change_password(
    body: ChangePasswordRequest, user: CurrentUser, session: SessionDep
) -> None:
    """Changes the password and signs the account out everywhere."""
    await AuthService(session).change_password(user, body.current_password, body.new_password)


# --- email ------------------------------------------------------------------------------


@router.post("/email/verify", response_model=UserRead)
async def verify_email(body: TokenRequest, session: SessionDep) -> UserRead:
    user = await AuthService(session).verify_email(body.token)
    return UserRead.model_validate(user)


@router.post(
    "/email/resend-verification",
    response_model=Accepted,
    status_code=202,
    dependencies=[_fa.Depends(_reset_limit)],
)
async def resend_verification(body: EmailRequest, session: SessionDep, mailer: MailerDep) -> Accepted:
    await AuthService(session).resend_verification(body.email, mailer)
    return Accepted()


@router.post(
    "/magic-link/request",
    response_model=Accepted,
    status_code=202,
    dependencies=[_fa.Depends(_reset_limit)],
)
async def request_magic_link(body: EmailRequest, session: SessionDep, mailer: MailerDep) -> Accepted:
    """Emails a one-time sign-in link."""
    await AuthService(session).request_magic_link(body.email, mailer)
    return Accepted()


@router.post("/magic-link/consume", response_model=TokenPair, dependencies=[_fa.Depends(_login_limit)])
async def consume_magic_link(body: TokenRequest, session: SessionDep) -> TokenPair:
    service = AuthService(session)
    user = await service.consume_magic_link(body.token)
    return await _tokens(service, user)


# --- password reset ---------------------------------------------------------------------


@router.post(
    "/password-reset/request",
    response_model=Accepted,
    status_code=202,
    dependencies=[_fa.Depends(_reset_limit)],
)
async def request_password_reset(
    body: PasswordResetRequest, session: SessionDep, mailer: MailerDep, sms: SmsDep
) -> Accepted:
    """Sends a reset link by email, or a code by SMS, to the account named in the body."""
    await AuthService(session).request_password_reset(body.email, body.phone, mailer, sms)
    return Accepted()


@router.post("/password-reset/confirm", status_code=204, dependencies=[_fa.Depends(_reset_limit)])
async def confirm_password_reset(body: PasswordResetConfirm, session: SessionDep) -> None:
    """Sets a new password and signs the account out everywhere."""
    await AuthService(session).confirm_password_reset(
        body.new_password, body.token, body.phone, body.code
    )
