"""Dependencies for protecting your own routes.

    from app.auth.deps import CurrentUser, require_roles

    @router.get("/reports", dependencies=[Depends(require_roles("admin"))])
    async def reports(user: CurrentUser): ...
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import config, security
from app.auth.models import AuthUser
from app.auth.service import effective_roles
from app.core.errors import AppError
from app.db import SessionDep

_bearer = HTTPBearer(auto_error=False, description="Access token from /auth/login")


def _unauthorized(message: str = "authentication required") -> AppError:
    return AppError("unauthorized", message, 401)


async def get_current_user(
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
        user_id = uuid.UUID(str(claims["sub"]))
    except (security.InvalidTokenError, KeyError, ValueError) as exc:
        raise _unauthorized("invalid or expired access token") from exc
    user = await session.get(AuthUser, user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise _unauthorized("invalid or expired access token")
    return user


CurrentUser = Annotated[AuthUser, Depends(get_current_user)]


def require_roles(*names: str) -> Callable[[AuthUser], Awaitable[AuthUser]]:
    """Allow users holding any of `names`, directly or through role inheritance."""

    async def dependency(user: CurrentUser) -> AuthUser:
        if not effective_roles(user.roles) & set(names):
            raise AppError("forbidden", "you do not have permission to do that", 403)
        return user

    return dependency
