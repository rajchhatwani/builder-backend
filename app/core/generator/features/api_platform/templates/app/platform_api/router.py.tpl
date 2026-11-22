"""API platform admin routes (generated): /platform/...

Issuing and revoking keys and installing apps is for the roles in settings.ROLES and nobody else (default deny),
scoped to the caller's tenant. These routes accept a signed-in user's token only: an API key never opens them."""

import datetime as _dt
import uuid as _uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.auth.deps import require_roles
from app.auth.models import AuthUser
from app.db import SessionDep
from app.platform_api import events, service, settings

router = APIRouter(prefix="/platform", tags=["platform"])
_roles = require_roles(*settings.ROLES)


async def _admin(user: Annotated[AuthUser, Depends(_roles)]) -> AuthUser:
    service.require_tenant(user)  # a multi-tenant project refuses an account that belongs to no tenant
    return user


Admin = Annotated[AuthUser, Depends(_admin)]


class CatalogueEntity(BaseModel):
    entity: str
    plural_path: str
    fields: list[str]
    sandbox: bool


class Catalogue(BaseModel):
    entities: list[CatalogueEntity]
    rate_limit: str
    sandbox_rate_limit: str
    key_ttl_days: int


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scopes: list[str] = Field(min_length=1, max_length=64)
    environment: Literal["sandbox", "prod"]
    ttl_days: int | None = Field(default=None, ge=1, le=settings.KEY_TTL_DAYS)


class KeyCreated(BaseModel):
    id: _uuid.UUID
    name: str
    prefix: str
    environment: str
    scopes: list[str]
    expires_at: _dt.datetime
    created_at: _dt.datetime
    key: str  # shown once, never stored


class KeyOut(BaseModel):
    id: _uuid.UUID
    name: str
    prefix: str
    kind: str
    app: str | None
    environment: str
    scopes: list[str]
    created_at: _dt.datetime
    expires_at: _dt.datetime
    revoked_at: _dt.datetime | None
    last_used_at: _dt.datetime | None
    status: Literal["active", "revoked", "expired"]


class AppOut(BaseModel):
    name: str
    title: str
    scopes: list[str]
    events: list[str]
    installed: bool
    installation_id: _uuid.UUID | None
    granted_scopes: list[str]
    installed_at: _dt.datetime | None


class InstallIn(BaseModel):
    scopes: list[str] | None = Field(default=None, max_length=64)


class InstallOut(BaseModel):
    installation_id: _uuid.UUID
    app: str
    granted_scopes: list[str]
    token: str  # shown once
    signing_secret: str  # shown once


class UninstallOut(BaseModel):
    installation_id: _uuid.UUID
    status: Literal["uninstalled"]


class AuditOut(BaseModel):
    model_config = {"from_attributes": True}

    id: _uuid.UUID
    at: _dt.datetime
    actor: str
    action: str
    target: str | None
    detail: dict[str, Any]


@router.get("/catalogue", response_model=Catalogue)
async def catalogue(user: Admin) -> Any:  # noqa: ARG001
    return service.catalogue()


@router.post("/keys", response_model=KeyCreated, status_code=201)
async def create_key(body: KeyIn, session: SessionDep, user: Admin) -> Any:
    row, plaintext = await service.create_key(session, user, body.name, body.scopes, body.environment, body.ttl_days)
    return {**service.key_view(row), "key": plaintext}


@router.get("/keys", response_model=list[KeyOut])
async def list_keys(session: SessionDep, user: Admin) -> Any:
    return [service.key_view(row) for row in await service.list_keys(session, user)]


@router.post("/keys/{key_id}/revoke", response_model=KeyOut)
async def revoke_key(key_id: _uuid.UUID, session: SessionDep, user: Admin) -> Any:
    return service.key_view(await service.revoke_key(session, user, key_id))


@router.get("/apps", response_model=list[AppOut])
async def list_apps(session: SessionDep, user: Admin) -> Any:
    return await service.list_apps(session, user)


@router.post("/apps/{name}/install", response_model=InstallOut, status_code=201)
async def install_app(name: str, body: InstallIn, session: SessionDep, user: Admin) -> Any:
    row, token = await service.install_app(session, user, name, body.scopes)
    return {
        "installation_id": row.id,
        "app": name,
        "granted_scopes": list(row.scopes),
        "token": token,
        "signing_secret": events.signing_secret_for(row.id),
    }


@router.post("/apps/{name}/uninstall", response_model=UninstallOut)
async def uninstall_app(name: str, session: SessionDep, user: Admin) -> Any:
    row = await service.uninstall_app(session, user, name)
    return {"installation_id": row.id, "status": "uninstalled"}


@router.get("/audit", response_model=list[AuditOut])
async def audit_log(
    session: SessionDep,
    user: Admin,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> Any:
    return await service.list_audit(session, user, limit, offset)
