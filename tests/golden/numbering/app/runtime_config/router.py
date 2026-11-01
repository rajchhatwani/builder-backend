"""Routes of the runtime configuration (generated): settings, lists, sequence counters.

Reads need the roles a definition lists (none listed = any caller). Writes need one of the
definition's `edit_roles`; a definition with none cannot be changed at run time."""

import uuid as _uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import access as _access
from app.auth.service import effective_roles
from app.core.errors import AppError, NotFoundError
from app.db import SessionDep
from app.runtime_config import sequences as _sequences
from app.runtime_config import settings as _settings
from app.runtime_config.definitions import SEQUENCES, SETTINGS

router = APIRouter(prefix="/config", tags=["runtime config"])
MULTI_TENANT = True
NIL_TENANT = _uuid.UUID(int=0)

_caller = _access.access_dependency(authenticate=True)
Caller = Annotated[_access.Access, Depends(_caller)]


def _tenant(access: _access.Access) -> _uuid.UUID:
    if not MULTI_TENANT:
        return NIL_TENANT
    if access.caller_tenant_id is None:
        raise AppError("forbidden", "you do not belong to a tenant", 403)
    return access.caller_tenant_id  # type: ignore[no-any-return]


def _holds(access: _access.Access, roles: list[str]) -> bool:
    held = effective_roles(access.user.roles) if access.user is not None else set()
    return bool(held & set(roles))


def _require(access: _access.Access, roles: list[str]) -> None:
    # An empty list means nobody: the definition is not editable at run time.
    if not _holds(access, roles):
        raise AppError("forbidden", "you do not have permission to do that", 403)


class SettingOut(BaseModel):
    key: str
    type: str
    label: str | None
    description: str | None
    value: object
    default: object
    is_default: bool
    editable: bool


class SettingIn(BaseModel):
    value: object = Field(...)


def _setting_out(key: str, row: object, editable: bool) -> SettingOut:
    d = SETTINGS[key]
    stored = getattr(row, "value", d["default"]) if row is not None else d["default"]
    return SettingOut(
        key=key,
        type=d["type"],
        label=d["label"],
        description=d["description"],
        value=stored,
        default=d["default"],
        is_default=row is None,
        editable=editable,
    )


@router.get("/settings", response_model=list[SettingOut])
async def list_settings(
    session: SessionDep,
    access: Caller,
) -> list[SettingOut]:
    rows = await _settings.stored_values(session, _tenant(access))
    return [
        _setting_out(key, rows.get(key), _holds(access, d["edit_roles"]))
        for key, d in sorted(SETTINGS.items())
        if not d["read_roles"] or _holds(access, d["read_roles"])
    ]


@router.put("/settings/{key}", response_model=SettingOut)
async def put_setting(key: str, body: SettingIn, session: SessionDep, access: Caller) -> SettingOut:
    if key not in SETTINGS:
        raise NotFoundError("setting not found")
    _require(access, SETTINGS[key]["edit_roles"])
    tenant = _tenant(access)
    await _settings.set_setting(
        session, key, body.value, tenant, access.user.id if access.user is not None else None
    )
    await session.commit()
    return _setting_out(key, (await _settings.stored_values(session, tenant)).get(key), True)


@router.delete("/settings/{key}", status_code=204)
async def reset_setting(key: str, session: SessionDep, access: Caller) -> None:
    if key not in SETTINGS:
        raise NotFoundError("setting not found")
    _require(access, SETTINGS[key]["edit_roles"])
    await _settings.reset_setting(session, key, _tenant(access))
    await session.commit()


class SequenceOut(BaseModel):
    name: str
    per_tenant: bool
    reset_yearly: bool
    next_number: str  # what the next caller would get (informational; taking one needs the code helper)


@router.get("/sequences", response_model=list[SequenceOut])
async def get_sequences(session: SessionDep, access: Caller) -> list[SequenceOut]:
    tenant = _tenant(access)
    return [
        SequenceOut(
            name=name,
            per_tenant=d["per_tenant"],
            reset_yearly=d["reset_yearly"],
            next_number=await _sequences.peek(session, name, tenant_id=tenant),
        )
        for name, d in sorted(SEQUENCES.items())
        if _holds(access, d["view_roles"])
    ]
