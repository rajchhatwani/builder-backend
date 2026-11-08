"""Dependencies for protecting your own routes.

    from app.auth.deps import CurrentUser, require_roles

    @router.get("/reports", dependencies=[Depends(require_roles("admin"))])
    async def reports(user: CurrentUser): ...

The caller sends a Keycloak access token as `Authorization: Bearer <token>`.
"""

import os
from collections.abc import Awaitable, Callable
from typing import Annotated

import structlog
from fastapi import Depends, Request
from fastapi.security import OAuth2AuthorizationCodeBearer

from app.auth import config, identity, oidc, service
from app.auth.models import AuthTenant, AuthUser
from app.auth.service import effective_roles
from app.core.errors import AppError
from app.db import SessionDep

logger = structlog.get_logger()


def _keycloak_url(endpoint: str) -> str:
    """Where Swagger UI sends you to sign in. Only used for the /docs "Authorize" button;
    tokens are verified against the settings in app/auth/config.py."""
    base = os.environ.get("KEYCLOAK_PUBLIC_URL", "http://localhost:8081").rstrip("/")
    return f"{base}/realms/{config.REALM}/protocol/openid-connect/{endpoint}"


_bearer = OAuth2AuthorizationCodeBearer(
    authorizationUrl=_keycloak_url("auth"),
    tokenUrl=_keycloak_url("token"),
    auto_error=False,
    description="Access token issued by Keycloak",
)


def _unauthorized(message: str = "authentication required") -> AppError:
    return AppError("unauthorized", message, 401)


async def get_current_user(
    request: Request,
    session: SessionDep,
    raw_token: Annotated[str | None, Depends(_bearer)],
) -> AuthUser:
    if raw_token is None:
        raise _unauthorized()
    try:
        token = await oidc.verify_access_token(raw_token)
    except oidc.KeysUnavailableError as exc:
        logger.error("auth_keys_unavailable", reason=str(exc))
        raise AppError("auth_unavailable", "sign-in is temporarily unavailable", 503) from exc
    except oidc.InvalidTokenError as exc:
        # The reason is for the log only; the caller learns nothing about what was wrong.
        logger.info("token_rejected", reason=str(exc))
        raise _unauthorized("invalid or expired access token") from exc
    if config.EMAIL_VERIFICATION_REQUIRED and not token.email_verified:
        raise AppError("email_not_verified", "verify your email address to continue", 403)
    if config.MULTI_TENANT:
        if not token.organizations:
            raise AppError(
                "no_organization",
                "your account does not belong to an organization, or belongs to several: "
                "sign in with the scope organization:<alias> to choose one",
                403,
            )
        if len(token.organizations) > 1:
            raise AppError(
                "organization_required",
                "sign in to one organization at a time (request the scope organization:<alias>)",
                403,
            )
    user = await service.sync_user(session, token)
    if user is None:
        raise _unauthorized("invalid or expired access token")
    if token.sid is not None and not await identity.open_session(
        session, user.id, token.issuer, token.sid
    ):
        # Keycloak told us (back-channel logout) that this sign-in is over.
        await session.rollback()
        raise _unauthorized("invalid or expired access token")
    request.state.auth_context = {
        "issuer": token.issuer,
        "subject": token.sub,
        "session_id": token.sid,
        "auth_time": token.auth_time,
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
