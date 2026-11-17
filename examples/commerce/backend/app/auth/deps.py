"""Dependencies for protecting your own routes.

    from app.auth.deps import CurrentUser, require_roles

    @router.get("/reports", dependencies=[Depends(require_roles("admin"))])
    async def reports(user: CurrentUser): ...
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import config, identity, security
from app.auth.models import AuthTenant, AuthUser
from app.auth.service import effective_roles
from app.core.errors import AppError
from app.db import SessionDep

_bearer = HTTPBearer(auto_error=False, description="Access token from /auth/login")


def _unauthorized(message: str = "authentication required") -> AppError:
    return AppError("unauthorized", message, 401)


async def get_current_user(
    request: Request,
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthUser:
    if credentials is None:
        raise _unauthorized()
    try:
        claims = security.decode_jwt(
            credentials.credentials, config.get_auth_settings().jwt_key
        )
        if claims.get("type") != "access":
            raise security.InvalidTokenError("not an access token")
        if claims.get("iss") != config.ISSUER:
            raise security.InvalidTokenError("wrong issuer")
        subject = claims["sub"]
        if not identity.subject_is_valid(subject):
            raise security.InvalidTokenError("bad subject")
    except (security.InvalidTokenError, KeyError) as exc:
        raise _unauthorized("invalid or expired access token") from exc
    # The token names an identity, not a user id: look the local user up through it.
    user_id = await identity.find_user_id(session, config.ISSUER, subject)
    user = await session.get(AuthUser, user_id) if user_id is not None else None
    if user is None or not user.is_active or user.deleted_at is not None:
        raise _unauthorized("invalid or expired access token")
    sid = claims.get("sid")
    if isinstance(sid, str) and not await identity.session_is_live(session, config.ISSUER, sid):
        raise _unauthorized("invalid or expired access token")
    request.state.auth_context = {
        "issuer": config.ISSUER,
        "subject": subject,
        "session_id": sid if isinstance(sid, str) else None,
        "auth_time": claims.get("iat") if isinstance(claims.get("iat"), int) else None,
    }
    return user


CurrentUser = Annotated[AuthUser, Depends(get_current_user)]


async def get_principal(request: Request, user: CurrentUser, session: SessionDep) -> identity.Principal:
    """The caller as a `Principal`: use this in your own code instead of reading token claims."""
    context = request.state.auth_context
    tenant_id = getattr(user, "tenant_id", None)
    tenant = await session.get(AuthTenant, tenant_id) if tenant_id is not None else None
    return identity.Principal(
        user_id=user.id,
        issuer=context["issuer"],
        subject=context["subject"],
        tenant_id=tenant_id,
        tenant_external_ref=tenant.external_ref if tenant is not None else None,
        roles=tuple(sorted(effective_roles(user.roles))),
        session_id=context["session_id"],
        auth_time=context["auth_time"],
    )


CurrentPrincipal = Annotated[identity.Principal, Depends(get_principal)]


def require_roles(*names: str) -> Callable[[AuthUser], Awaitable[AuthUser]]:
    """Allow users holding any of `names`, directly or through role inheritance."""

    async def dependency(user: CurrentUser) -> AuthUser:
        if not effective_roles(user.roles) & set(names):
            raise AppError("forbidden", "you do not have permission to do that", 403)
        return user

    return dependency
