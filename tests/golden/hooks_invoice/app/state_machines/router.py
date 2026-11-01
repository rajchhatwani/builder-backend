"""Transition routes for entities with a state machine (generated)."""

import datetime as _dt
import uuid as _uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import access as _access
from app.auth.service import effective_roles
from app.crud.invoices import InvoiceRepository
from app.db import SessionDep
from app.routers.invoices import _ACCESS as _ACCESS_invoices
from app.schemas.invoices import InvoiceRead
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
_access_invoices = _ACCESS_invoices["get"]


def _roles_invoices(access: _access.Access) -> set[str]:
    return effective_roles(access.user.roles) if access.user is not None else set()


@router.get("/invoices/{item_id}/transitions", response_model=list[TransitionInfo])
async def list_invoices_transitions(
    item_id: _uuid.UUID,
    session: SessionDep,
    access: Annotated[_access.Access, Depends(_access_invoices)],
) -> list[dict[str, object]]:
    item = await InvoiceRepository(session, **access.repo_kwargs).get(item_id)
    return engine.available("Invoice", item, _roles_invoices(access))


@router.post("/invoices/{item_id}/transitions/{name}", response_model=InvoiceRead)
async def apply_invoices_transition(
    item_id: _uuid.UUID,
    name: str,
    session: SessionDep,
    access: Annotated[_access.Access, Depends(_access_invoices)],
) -> InvoiceRead:
    repo = InvoiceRepository(session, **access.repo_kwargs)
    item = await engine.apply(
        repo,
        "Invoice",
        item_id,
        name,
        roles=_roles_invoices(access),
        actor_id=access.user.id if access.user is not None else None,
    )
    return InvoiceRead.model_validate(item)


@router.get("/invoices/{item_id}/state-history", response_model=list[StateChange])
async def invoices_state_history(
    item_id: _uuid.UUID,
    session: SessionDep,
    access: Annotated[_access.Access, Depends(_access_invoices)],
) -> list[StateChange]:
    await InvoiceRepository(session, **access.repo_kwargs).get(item_id)
    rows = await engine.history(session, "Invoice", item_id)
    return [StateChange.model_validate(row) for row in rows]
