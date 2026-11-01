"""HTTP routes for authentication (generated)."""
import typing as _t
import uuid as _uuid

import fastapi as _fa

from app.auth import config
from app.auth.delivery import Mailer, SmsSender, get_mailer, get_sms_sender
from app.auth.deps import CurrentUser, require_roles
from app.auth.models import AuthUser
from app.auth.ratelimit import FailureRateLimiter, RateLimiter
from app.auth.schemas import (
    Accepted,
    ChangePasswordRequest,
    EmailRequest,
    InvitationCreate,
    InvitationRead,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TenantRead,
    TokenPair,
    TokenRequest,
    UserRead,
)
from app.auth.service import AuthService
from app.db import SessionDep

router = _fa.APIRouter(prefix="/auth", tags=["auth"])

MailerDep = _t.Annotated[Mailer, _fa.Depends(get_mailer)]
SmsDep = _t.Annotated[SmsSender, _fa.Depends(get_sms_sender)]

_login_limit = FailureRateLimiter("login", config.LOGIN_RATE_LIMIT)
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


@router.get("/tenant", response_model=TenantRead)
async def my_tenant(user: CurrentUser, session: SessionDep) -> TenantRead:
    """The tenant the signed-in user belongs to."""
    return TenantRead.model_validate(await AuthService(session).get_tenant(user))


@router.delete("/me", status_code=204)
async def delete_me(user: CurrentUser, session: SessionDep) -> None:
    """Permanently deletes the account and everything that belongs to it."""
    await AuthService(session).delete_account(user)


@router.post("/change-password", status_code=204)
async def change_password(
    body: ChangePasswordRequest, user: CurrentUser, session: SessionDep
) -> None:
    """Changes the password and signs the account out everywhere."""
    await AuthService(session).change_password(user, body.current_password, body.new_password)


# --- invitations ------------------------------------------------------------------------

AdminDep = _t.Annotated[AuthUser, _fa.Depends(require_roles("admin"))]


@router.post("/invitations", response_model=InvitationRead, status_code=201)
async def create_invitation(
    body: InvitationCreate, admin: AdminDep, session: SessionDep, mailer: MailerDep
) -> InvitationRead:
    """Emails a link that lets one address register."""
    invitation = await AuthService(session).create_invitation(
        admin, body.email, list(body.roles), mailer
    )
    return InvitationRead.model_validate(invitation)


@router.get("/invitations", response_model=list[InvitationRead])
async def list_invitations(admin: AdminDep, session: SessionDep) -> list[InvitationRead]:
    """Invitations that are still waiting to be accepted (your tenant only)."""
    invitations = await AuthService(session).list_invitations(admin)
    return [InvitationRead.model_validate(i) for i in invitations]


@router.delete("/invitations/{invitation_id}", status_code=204)
async def revoke_invitation(
    invitation_id: _uuid.UUID, admin: AdminDep, session: SessionDep
) -> None:
    await AuthService(session).revoke_invitation(admin, invitation_id)


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
