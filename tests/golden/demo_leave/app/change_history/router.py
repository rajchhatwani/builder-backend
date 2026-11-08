"""Change-history routes (generated): GET /<entity>/{id}/history, for the roles the spec lists.

The caller needs one of the entity's `view_roles` and must be allowed to read the record itself
(its own access rule, tenant and row scope included)."""

import datetime as _dt
import uuid as _uuid
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.auth import access as _access
from app.auth.service import effective_roles
from app.change_history.definitions import HISTORY
from app.change_history.models import Change
from app.core.errors import AppError
from app.crud.employees import EmployeeRepository
from app.crud.leave_requests import LeaveRequestRepository
from app.db import SessionDep
from app.routers.employees import _ACCESS as _ACCESS_employees
from app.routers.leave_requests import _ACCESS as _ACCESS_leave_requests

router = APIRouter(tags=["change history"])


class ChangeOut(BaseModel):
    model_config = {"from_attributes": True}

    id: _uuid.UUID
    field: str
    old_value: str | None
    new_value: str | None
    op: str
    actor_id: _uuid.UUID | None
    created_at: _dt.datetime
_access_employees = _ACCESS_employees["get"]


@router.get("/employees/{item_id}/history", response_model=list[ChangeOut])
async def employees_history(
    item_id: _uuid.UUID,
    session: SessionDep,
    access: Annotated[_access.Access, Depends(_access_employees)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> list[Change]:
    held = effective_roles(access.user.roles) if access.user is not None else set()
    if not held & set(HISTORY["Employee"]["view_roles"]):
        raise AppError("forbidden", "you do not have permission to do that", 403)
    await EmployeeRepository(session, **access.repo_kwargs).get(item_id)  # 404 when not visible
    rows = await session.execute(
        sa.select(Change)
        .where(Change.entity == "Employee", Change.record_id == item_id)
        .order_by(Change.created_at, Change.id)
        .limit(limit)
        .offset(offset)
    )
    return list(rows.scalars())
_access_leave_requests = _ACCESS_leave_requests["get"]


@router.get("/leave_requests/{item_id}/history", response_model=list[ChangeOut])
async def leave_requests_history(
    item_id: _uuid.UUID,
    session: SessionDep,
    access: Annotated[_access.Access, Depends(_access_leave_requests)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> list[Change]:
    held = effective_roles(access.user.roles) if access.user is not None else set()
    if not held & set(HISTORY["LeaveRequest"]["view_roles"]):
        raise AppError("forbidden", "you do not have permission to do that", 403)
    await LeaveRequestRepository(session, **access.repo_kwargs).get(item_id)  # 404 when not visible
    rows = await session.execute(
        sa.select(Change)
        .where(Change.entity == "LeaveRequest", Change.record_id == item_id)
        .order_by(Change.created_at, Change.id)
        .limit(limit)
        .offset(offset)
    )
    return list(rows.scalars())
