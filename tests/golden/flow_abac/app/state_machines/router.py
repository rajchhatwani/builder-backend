"""Transition routes for entities with a state machine (generated)."""

import datetime as _dt
import uuid as _uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import access as _access
from app.auth.service import effective_roles
from app.crud.tickets import TicketRepository
from app.db import SessionDep
from app.routers.tickets import _ACCESS as _ACCESS_tickets
from app.schemas.tickets import TicketRead
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
_access_tickets = _ACCESS_tickets["get"]
# A move changes the record: on policy entities the caller must pass the UPDATE decision as well.
_access_move_tickets = _ACCESS_tickets["update"]


def _roles_tickets(access: _access.Access) -> set[str]:
    return effective_roles(access.user.roles) if access.user is not None else set()


@router.get("/tickets/{item_id}/transitions", response_model=list[TransitionInfo])
async def list_tickets_transitions(
    item_id: _uuid.UUID,
    session: SessionDep,
    access: Annotated[_access.Access, Depends(_access_tickets)],
) -> list[dict[str, object]]:
    item = await TicketRepository(session, **access.repo_kwargs).get(item_id)
    return engine.available("Ticket", item, _roles_tickets(access))


@router.post("/tickets/{item_id}/transitions/{name}", response_model=TicketRead)
async def apply_tickets_transition(
    item_id: _uuid.UUID,
    name: str,
    session: SessionDep,
    access: Annotated[_access.Access, Depends(_access_move_tickets)],
) -> TicketRead:
    repo = TicketRepository(session, **access.repo_kwargs)
    item = await engine.apply(
        repo,
        "Ticket",
        item_id,
        name,
        roles=_roles_tickets(access),
        actor_id=access.user.id if access.user is not None else None,
    )
    return TicketRead.model_validate(item)


@router.get("/tickets/{item_id}/state-history", response_model=list[StateChange])
async def tickets_state_history(
    item_id: _uuid.UUID,
    session: SessionDep,
    access: Annotated[_access.Access, Depends(_access_tickets)],
) -> list[StateChange]:
    await TicketRepository(session, **access.repo_kwargs).get(item_id)
    rows = await engine.history(session, "Ticket", item_id)
    return [StateChange.model_validate(row) for row in rows]
