"""Compliance routes (generated): /compliance/...

Administration (legal holds, consent, retention, exports, audit) is for the roles in settings.ROLES and nobody else.
Asking for break-glass access is for settings.BREAK_GLASS["roles"]; reading with a grant needs the grant's owner."""

import datetime as _dt
import uuid as _uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.auth.deps import CurrentUser, require_roles
from app.auth.models import AuthUser
from app.auth.service import effective_roles
from app.compliance import service, settings
from app.db import SessionDep

router = APIRouter(prefix="/compliance", tags=["compliance"])
_roles = require_roles(*settings.ROLES)


async def _admin(user: Annotated[AuthUser, Depends(_roles)]) -> AuthUser:
    service.require_tenant(user)  # a multi-tenant project refuses an account that belongs to no tenant
    return user


Admin = Annotated[AuthUser, Depends(_admin)]


class HoldIn(BaseModel):
    entity: str
    record_id: _uuid.UUID | None = None  # null = the whole entity
    reason: str = Field(min_length=3, max_length=500)


class HoldOut(BaseModel):
    model_config = {"from_attributes": True}

    id: _uuid.UUID
    entity: str
    record_id: _uuid.UUID | None
    reason: str
    placed_by: str
    placed_at: _dt.datetime
    released_at: _dt.datetime | None
    released_by: str | None


class ConsentIn(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    purpose: str


class ConsentOut(BaseModel):
    model_config = {"from_attributes": True}

    id: _uuid.UUID
    subject: str
    purpose: str
    granted_at: _dt.datetime
    withdrawn_at: _dt.datetime | None


class ConsentCheck(BaseModel):
    subject: str
    purpose: str
    granted: bool


class RetentionIn(BaseModel):
    dry_run: bool = False


class BreakGlassIn(BaseModel):
    reason: str = Field(min_length=10, max_length=500)
    entities: list[str] = Field(min_length=1, max_length=20)
    minutes: int = Field(ge=1, le=240)


class GrantOut(BaseModel):
    model_config = {"from_attributes": True}

    id: _uuid.UUID
    user_id: _uuid.UUID
    role: str
    entity_scope: list[str]
    granted_at: _dt.datetime
    expires_at: _dt.datetime
    revoked_at: _dt.datetime | None


class ExportIn(BaseModel):
    entity: str


class AuditOut(BaseModel):
    model_config = {"from_attributes": True}

    id: _uuid.UUID
    at: _dt.datetime
    actor: str
    action: str
    entity: str | None
    record_id: _uuid.UUID | None
    detail: dict[str, Any]


# --- legal holds ---------------------------------------------------------------------------------------------


@router.post("/legal-holds", response_model=HoldOut, status_code=201)
async def place_hold(body: HoldIn, session: SessionDep, user: Admin) -> Any:
    return await service.place_hold(session, user, body.entity, body.record_id, body.reason)


@router.get("/legal-holds", response_model=list[HoldOut])
async def list_holds(session: SessionDep, user: Admin, active: bool = True) -> Any:
    return await service.list_holds(session, user, active_only=active)


@router.delete("/legal-holds/{hold_id}", response_model=HoldOut)
async def release_hold(hold_id: _uuid.UUID, session: SessionDep, user: Admin) -> Any:
    return await service.release_hold(session, user, hold_id)


# --- consent -------------------------------------------------------------------------------------------------


@router.post("/consents", response_model=ConsentOut, status_code=201)
async def grant_consent(body: ConsentIn, session: SessionDep, user: Admin) -> Any:
    return await service.grant_consent(session, user, body.subject, body.purpose)


@router.post("/consents/withdraw")
async def withdraw_consent(body: ConsentIn, session: SessionDep, user: Admin) -> dict[str, int]:
    return {"withdrawn": await service.withdraw_consent(session, user, body.subject, body.purpose)}


@router.get("/consents/check", response_model=ConsentCheck)
async def check_consent(session: SessionDep, user: Admin, subject: str, purpose: str) -> ConsentCheck:
    return ConsentCheck(subject=subject, purpose=purpose, granted=await service.has_consent(session, subject, purpose))


# --- retention -----------------------------------------------------------------------------------------------


@router.post("/retention/run")
async def run_retention(body: RetentionIn, session: SessionDep, user: Admin) -> dict[str, Any]:
    return await service.run_retention(session, str(user.id), dry_run=body.dry_run, tenant=service.require_tenant(user))


# --- break-glass ---------------------------------------------------------------------------------------------


@router.post("/break-glass", response_model=GrantOut, status_code=201)
async def ask_break_glass(body: BreakGlassIn, session: SessionDep, user: CurrentUser) -> Any:
    return await service.grant_break_glass(session, user, body.reason, body.entities, body.minutes)


@router.get("/break-glass", response_model=list[GrantOut])
async def list_grants(session: SessionDep, user: Admin) -> Any:
    return await service.list_grants(session, user)


@router.get("/break-glass/{grant_id}/records/{entity}")
async def break_glass_records(
    grant_id: _uuid.UUID,
    entity: str,
    session: SessionDep,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> list[dict[str, Any]]:
    return await service.break_glass_read(session, user, grant_id, entity, limit=limit, offset=offset)


@router.post("/break-glass/{grant_id}/revoke", response_model=GrantOut)
async def revoke_break_glass(grant_id: _uuid.UUID, session: SessionDep, user: CurrentUser) -> Any:
    is_admin = bool(effective_roles(user.roles) & set(settings.ROLES))
    return await service.revoke_break_glass(session, user, grant_id, is_admin=is_admin)


# --- export + audit ------------------------------------------------------------------------------------------


@router.post("/exports")
async def export(body: ExportIn, session: SessionDep, user: Admin) -> dict[str, Any]:
    return await service.export_entity(session, user, body.entity)


@router.get("/audit", response_model=list[AuditOut])
async def audit_log(
    session: SessionDep, user: Admin, limit: Annotated[int, Query(ge=1, le=500)] = 100, action: str | None = None
) -> Any:
    return await service.list_audit(session, user, limit=limit, action=action)
