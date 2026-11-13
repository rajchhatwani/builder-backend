"""Shared helpers of the operations pack (generated): role checks, tenant scoping."""

import typing as _t
import uuid as _uuid

from fastapi import Depends

from app.auth.deps import CurrentUser
from app.auth.models import AuthUser
from app.auth.service import effective_roles
from app.core.errors import AppError

Tenant = _uuid.UUID | None


def allow(user: AuthUser, roles: tuple[str, ...]) -> AuthUser:
    """An empty role tuple means any signed-in user."""
    if roles and not effective_roles(user.roles) & set(roles):
        raise AppError("forbidden", "you do not have permission to do that", 403)
    return user


def role_dependency(roles: tuple[str, ...]) -> _t.Any:
    async def _check(user: CurrentUser) -> AuthUser:
        return allow(user, roles)

    return Depends(_check)


def tenant_of(user: _t.Any, multi_tenant: bool) -> Tenant:
    if not multi_tenant:
        return None
    tenant = getattr(user, "tenant_id", None)
    if tenant is None:
        raise AppError("forbidden", "this needs a caller that belongs to a tenant", 403)
    return _t.cast(_uuid.UUID, tenant)


def scoped(stmt: _t.Any, model: _t.Any, tenant: Tenant) -> _t.Any:
    return stmt.where(model.tenant_id == tenant) if tenant is not None else stmt


def tenant_values(tenant: Tenant) -> dict[str, _t.Any]:
    return {"tenant_id": tenant} if tenant is not None else {}
