"""Per-route access control built from the project's permissions (generated).

Each entity route that has a permission gets an `access_dependency(...)` (see its router).
It checks the caller's roles and returns an `Access` that tells the repository which rows
the caller may touch. Role inheritance applies: a role holds its parent's rights.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.auth.deps import CurrentUser
from app.auth.models import AuthUser
from app.auth.service import effective_roles
from app.core.errors import AppError

# The role that role_scoped rules let see every row.
ADMIN_ROLE = "admin"


@dataclass(frozen=True)
class Access:
    user: AuthUser | None = None
    # column -> value the repository restricts every query to
    scope: dict[str, Any] = field(default_factory=dict)
    # recorded as created_by_id on new rows
    owner_id: uuid.UUID | None = None
    # recorded as tenant_id on new rows (tenant-scoped entities)
    tenant_id: uuid.UUID | None = None
    # the signed-in caller's tenant, even for entities that are not tenant-scoped themselves:
    # a reference to a tenant-scoped row must stay inside it
    caller_tenant_id: uuid.UUID | None = None

    @property
    def repo_kwargs(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "owner_id": self.owner_id,
            "tenant_id": self.tenant_id,
            "caller_tenant_id": self.caller_tenant_id,
            "caller": self.user,
        }


def build_access(
    user: AuthUser | None,
    *,
    roles: tuple[str, ...] = (),
    owner: bool = False,
    admin_sees_all: bool = False,
    match: tuple[str, Any] | None = None,
    stamp: bool = False,
    tenant: bool = False,
) -> Access:
    held = effective_roles(user.roles) if user is not None else set()
    if roles and not held & set(roles):
        raise AppError("forbidden", "you do not have permission to do that", 403)
    scope: dict[str, Any] = {}
    if owner and user is not None and not (admin_sees_all and ADMIN_ROLE in held):
        scope["created_by_id"] = user.id
    if match is not None:
        scope[match[0]] = match[1]
    tenant_id = None
    if tenant and user is not None:
        # Every query of a tenant-scoped entity is confined to the caller's own tenant.
        tenant_id = user.tenant_id  # type: ignore[attr-defined]
        scope["tenant_id"] = tenant_id
    caller_tenant_id = getattr(user, "tenant_id", None) if user is not None else None
    return Access(
        user,
        scope,
        user.id if stamp and user is not None else None,
        tenant_id,
        caller_tenant_id,
    )


def access_dependency(
    *,
    roles: tuple[str, ...] = (),
    owner: bool = False,
    admin_sees_all: bool = False,
    match: tuple[str, Any] | None = None,
    stamp: bool = False,
    authenticate: bool = False,
    tenant: bool = False,
) -> Callable[..., Awaitable[Access]]:
    """Dependency for one route.

    roles           any one of these is required (none listed = no role needed)
    owner           only rows the caller created (admin_sees_all lifts that for admins)
    match           only rows where column == value
    stamp           record the caller as the creator of new rows
    authenticate    a signed-in caller is required even when no role is
    tenant          only rows of the caller's tenant; new rows get that tenant
    """
    if roles or owner or stamp or authenticate or tenant:

        async def with_user(user: CurrentUser) -> Access:
            return build_access(
                user,
                roles=roles,
                owner=owner,
                admin_sees_all=admin_sees_all,
                match=match,
                stamp=stamp,
                tenant=tenant,
            )

        return with_user

    async def anonymous() -> Access:
        return build_access(None, match=match)

    return anonymous
