"""Keeps this project's user rows in step with Keycloak (generated)."""

import datetime as dt
import uuid
from typing import Any

import structlog
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import config
from app.auth.models import AuthTenant, AuthUser
from app.auth.oidc import VerifiedToken, coerce_attribute

logger = structlog.get_logger()


def effective_roles(roles: list[str]) -> set[str]:
    """The user's roles plus every role they inherit from."""
    result: set[str] = set()
    pending = list(roles)
    while pending:
        role = pending.pop()
        if role in result:
            continue
        result.add(role)
        parent = config.ROLE_PARENTS.get(role)
        if parent is not None:
            pending.append(parent)
    return result


def roles_from_token(token: VerifiedToken) -> list[str]:
    """Known roles only (a role Keycloak knows but this project does not is ignored), plus the
    roles everyone holds."""
    known = {r for r in token.roles if r in config.ROLE_PARENTS}
    return sorted(known | set(config.DEFAULT_ROLES))


def tenant_of(token: VerifiedToken) -> tuple[uuid.UUID, str] | None:
    """The tenant (id, name) of a token issued for exactly one organization, else None."""
    if len(token.organizations) != 1:
        return None
    alias = token.organizations[0]
    return uuid.uuid5(config.TENANT_NAMESPACE, alias), alias


async def _ensure_tenant(session: AsyncSession, tenant_id: uuid.UUID, name: str) -> None:
    exists = await session.get(AuthTenant, tenant_id)
    if exists is not None:
        return
    await session.execute(
        insert(AuthTenant)
        .values(
            id=tenant_id,
            name=name,
            created_at=dt.datetime.now(dt.UTC),
            updated_at=dt.datetime.now(dt.UTC),
        )
        .on_conflict_do_nothing(index_elements=["id"])  # two first requests at once
    )
    await session.commit()


def _defaults() -> dict[str, Any]:
    """Values for custom fields that have a default, used when a user is first seen."""
    result: dict[str, Any] = {}
    for name, kind, max_length, allowed, default in config.CUSTOM_FIELDS:
        if default is not None:
            result[name] = coerce_attribute(kind, default, max_length, allowed)
    return result


async def sync_user(session: AsyncSession, token: VerifiedToken) -> AuthUser | None:
    """The profile row for a verified token: created on first sight, refreshed when the name,
    email, roles, organization or custom fields changed. None means this user is switched off
    or deleted here."""
    roles = roles_from_token(token)
    tenant = tenant_of(token) if config.MULTI_TENANT else None
    if tenant is not None:
        await _ensure_tenant(session, *tenant)
    user = await session.get(AuthUser, token.sub)
    if user is None:
        extra: dict[str, Any] = {**_defaults(), **token.attributes}
        if config.MULTI_TENANT:
            extra["tenant_id"] = tenant[0] if tenant else None
        await session.execute(
            insert(AuthUser)
            .values(
                id=token.sub,
                email=token.email,
                name=token.name,
                roles=roles,
                is_active=True,
                created_at=dt.datetime.now(dt.UTC),
                updated_at=dt.datetime.now(dt.UTC),
                **extra,
            )
            .on_conflict_do_nothing(index_elements=["id"])  # two first requests at once
        )
        await session.commit()
        user = await session.get(AuthUser, token.sub, populate_existing=True)
        if user is None:
            return None
        logger.info("user_created", user_id=str(user.id))
    if user.deleted_at is not None or not user.is_active:
        return None
    changed = False
    # Keycloak is the source of truth for these, so a rename or a role change takes effect on
    # the next request. A token without an email must not erase the one we know.
    if token.email is not None and user.email != token.email:
        user.email, changed = token.email, True
    if token.name is not None and user.name != token.name:
        user.name, changed = token.name, True
    if user.roles != roles:
        user.roles, changed = roles, True
    if config.MULTI_TENANT and tenant is not None and user.tenant_id != tenant[0]:  # type: ignore[attr-defined]
        user.tenant_id, changed = tenant[0], True  # type: ignore[attr-defined]
    # A field the token does not carry is left as it is: it may simply come from a client that
    # does not list it. Only a value that is present (even an invalid one) replaces the stored one.
    for field_name, value in token.attributes.items():
        if getattr(user, field_name) != value:
            setattr(user, field_name, value)
            changed = True
    if changed:
        await session.commit()
    return user


async def delete_account(session: AsyncSession, user: AuthUser) -> None:
    """Erases what this project knows about the user. Rows they created keep their id (so
    nothing dangles) but it no longer leads to a person. The Keycloak account itself is
    removed in Keycloak, and until then this user cannot sign in here again."""
    user.email = None
    user.name = None
    user.roles = []
    for field_name, *_ in config.CUSTOM_FIELDS:
        setattr(user, field_name, None)
    user.is_active = False
    user.deleted_at = dt.datetime.now(dt.UTC)
    await session.commit()
    logger.info("user_erased", user_id=str(user.id))
