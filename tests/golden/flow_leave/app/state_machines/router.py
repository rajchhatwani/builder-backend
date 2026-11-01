"""Transition routes for entities with a state machine (generated)."""

import datetime as _dt
import uuid as _uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import access as _access
from app.auth.service import effective_roles
from app.crud.leave_requests import LeaveRequestRepository
from app.db import SessionDep
from app.routers.leave_requests import _ACCESS as _ACCESS_leave_requests
from app.schemas.leave_requests import LeaveRequestRead
from app.state_machines import engine

router = APIRouter(tags=["state machines"])


class TransitionInfo(BaseModel):
    name: str
    to_state: str
    allowed: bool
    refused_because: str | None = None  # "role" or "guard"


class StateChange(BaseModel):
    model_config = {"from_attributes": True}

    transition: str
    from_state: str | None
    to_state: str
    actor_id: _uuid.UUID | None
    automatic: bool
    created_at: _dt.datetime
_access_leave_requests = _ACCESS_leave_requests["get"]


def _roles_leave_requests(access: _access.Access) -> set[str]:
    return effective_roles(access.user.roles) if access.user is not None else set()


@router.get("/leave_requests/{item_id}/transitions", response_model=list[TransitionInfo])
async def list_leave_requests_transitions(
    item_id: _uuid.UUID,
    session: SessionDep,
    access: Annotated[_access.Access, Depends(_access_leave_requests)],
) -> list[dict[str, object]]:
    item = await LeaveRequestRepository(session, **access.repo_kwargs).get(item_id)
    return engine.available("LeaveRequest", item, _roles_leave_requests(access))


@router.post("/leave_requests/{item_id}/transitions/{name}", response_model=LeaveRequestRead)
async def apply_leave_requests_transition(
    item_id: _uuid.UUID,
    name: str,
    session: SessionDep,
    access: Annotated[_access.Access, Depends(_access_leave_requests)],
) -> LeaveRequestRead:
    repo = LeaveRequestRepository(session, **access.repo_kwargs)
    item = await engine.apply(
        repo,
        "LeaveRequest",
        item_id,
        name,
        roles=_roles_leave_requests(access),
        actor_id=access.user.id if access.user is not None else None,
    )
    return LeaveRequestRead.model_validate(item)


@router.get("/leave_requests/{item_id}/state-history", response_model=list[StateChange])
async def leave_requests_state_history(
    item_id: _uuid.UUID,
    session: SessionDep,
    access: Annotated[_access.Access, Depends(_access_leave_requests)],
) -> list[StateChange]:
    await LeaveRequestRepository(session, **access.repo_kwargs).get(item_id)
    rows = await engine.history(session, "LeaveRequest", item_id)
    return [StateChange.model_validate(row) for row in rows]
