"""HTTP routes for authentication with Keycloak (generated).

Signing in, registering, password reset and token refresh all happen in Keycloak, so this
project only offers the caller's own profile."""
import datetime as _dt
import uuid as _uuid

import fastapi as _fa
import pydantic as _pd

from app.auth import config, identity, oidc, service
from app.auth.deps import CurrentUser
from app.core.errors import AppError
from app.db import SessionDep

router = _fa.APIRouter(prefix="/auth", tags=["auth"])


class UserRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    email: str | None
    name: str | None
    roles: list[str]
    created_at: _dt.datetime


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.delete("/me", status_code=204)
async def delete_me(user: CurrentUser, session: SessionDep) -> None:
    """Erases the caller's profile here. Their Keycloak account is deleted in Keycloak."""
    await service.delete_account(session, user)


@router.post("/backchannel-logout", status_code=204, include_in_schema=False)
async def backchannel_logout(request: _fa.Request, session: SessionDep) -> None:
    """Keycloak calls this when someone signs out elsewhere, so their session ends here too.
    Disabled (404) until AUTH_BACKCHANNEL_LOGOUT_ENABLED=true."""
    if not config.get_auth_settings().auth_backchannel_logout_enabled:
        raise AppError("not_found", "not found", 404)
    # A plain form post (application/x-www-form-urlencoded); parsed by hand so the project needs
    # no multipart library.
    try:
        logout_token = oidc.logout_token_from_form(await request.body())
    except oidc.InvalidTokenError as exc:
        raise AppError("invalid_token", "invalid logout token", 400) from exc
    try:
        verified = await oidc.verify_logout_token(logout_token)
    except oidc.KeysUnavailableError as exc:
        raise AppError("auth_unavailable", "sign-in is temporarily unavailable", 503) from exc
    except oidc.InvalidTokenError as exc:
        raise AppError("invalid_token", "invalid logout token", 400) from exc
    if verified.sid is not None:
        await identity.end_session(session, verified.issuer, verified.sid, "backchannel_logout")
    elif verified.sub is not None:
        user_id = await identity.find_user_id(session, verified.issuer, verified.sub)
        if user_id is not None:
            await identity.end_sessions_of_user(
                session, user_id, "backchannel_logout", issuer=verified.issuer
            )
