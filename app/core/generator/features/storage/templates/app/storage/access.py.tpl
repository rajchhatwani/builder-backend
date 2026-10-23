"""Who may do what with files (generated). Deny by default: a role list that is empty in the
settings means nobody may do it."""

import uuid

import sqlalchemy as sa

from app.auth.models import AuthUser
from app.auth.service import effective_roles
from app.core.errors import AppError
from app.storage import config
from app.storage.models import StorFile


def has_role(user: AuthUser, key: str) -> bool:
    return bool(effective_roles(user.roles) & set(config.ROLES.get(key, ())))


def require_role(user: AuthUser, key: str) -> None:
    if not has_role(user, key):
        raise AppError("forbidden", "you do not have permission to do that", 403)


def tenant_of(user: AuthUser) -> uuid.UUID | None:
    return getattr(user, "tenant_id", None) if config.MULTI_TENANT else None


def in_tenant(user: AuthUser) -> list[sa.ColumnElement[bool]]:
    return [StorFile.tenant_id == tenant_of(user)] if config.MULTI_TENANT else []


# Files a person can see in listings and download: available ones, or quarantined ones (so they
# can see why a file stopped working). Pending, deleting and erased files do not exist for them.
VISIBLE_STATUSES = ("clean", "quarantined")


def visible_to(user: AuthUser) -> list[sa.ColumnElement[bool]]:
    """Conditions for the files `user` may see: all of the tenant's (read_all), or their own and
    the shared ones (read). Everyone else gets a 403 here, never an empty list that hides it."""
    conditions: list[sa.ColumnElement[bool]] = [
        StorFile.status.in_(VISIBLE_STATUSES),
        *in_tenant(user),
    ]
    if has_role(user, "read_all"):
        return conditions
    require_role(user, "read")
    conditions.append(sa.or_(StorFile.created_by_id == user.id, StorFile.shared.is_(True)))
    return conditions
