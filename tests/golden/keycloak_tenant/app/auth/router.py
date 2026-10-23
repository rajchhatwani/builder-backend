"""HTTP routes for authentication with Keycloak (generated).

Signing in, registering, password reset and token refresh all happen in Keycloak, so this
project only offers the caller's own profile."""
import datetime as _dt
import typing as _t
import uuid as _uuid

import fastapi as _fa
import pydantic as _pd

from app.auth import service
from app.auth.deps import CurrentUser
from app.auth.models import AuthTenant
from app.core.errors import AppError
from app.db import SessionDep

router = _fa.APIRouter(prefix="/auth", tags=["auth"])


class UserRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    email: str | None
    name: str | None
    roles: list[str]
    tenant_id: _uuid.UUID | None
    age: int | None = None
    born: _dt.date | None = None
    company: str | None = None
    mobile: str | None = None
    newsletter: bool | None = None
    notes: str | None = None
    plan: _t.Literal['free', 'pro'] | None = None
    score: float | None = None
    site: str | None = None
    created_at: _dt.datetime


class TenantRead(_pd.BaseModel):
    model_config = _pd.ConfigDict(from_attributes=True)

    id: _uuid.UUID
    name: str


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.get("/tenant", response_model=TenantRead)
async def my_tenant(user: CurrentUser, session: SessionDep) -> TenantRead:
    """The tenant (Keycloak organization) the signed-in user is working in."""
    tenant = await session.get(AuthTenant, user.tenant_id)  # type: ignore[attr-defined]
    if tenant is None:  # unreachable: the user was placed in a tenant when they were seen
        raise AppError("not_found", "tenant not found", 404)
    return TenantRead.model_validate(tenant)


@router.delete("/me", status_code=204)
async def delete_me(user: CurrentUser, session: SessionDep) -> None:
    """Erases the caller's profile here. Their Keycloak account is deleted in Keycloak."""
    await service.delete_account(session, user)
