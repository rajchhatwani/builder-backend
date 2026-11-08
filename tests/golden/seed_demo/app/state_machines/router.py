"""Transition routes for entities with a state machine (generated)."""

import datetime as _dt
import uuid as _uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import access as _access
from app.auth.deps import CurrentUser
from app.auth.service import effective_roles
from app.core.errors import AppError
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


async def _can_replace_invoices(user: CurrentUser) -> _access.Access | AppError:
    """The entity's own replace access for this caller; a refusal is kept, not raised: only a transition
    with no `roles` needs it."""
    try:
        return await _ACCESS_invoices["replace"](user)
    except AppError as refused:
        return refused


async def _can_update_invoices(user: CurrentUser) -> _access.Access | AppError:
    """The entity's own update access for this caller; a refusal is kept, not raised: only a transition
    with no `roles` needs it."""
    try:
        return await _ACCESS_invoices["update"](user)
    except AppError as refused:
        return refused


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
    can_replace: Annotated[_access.Access | AppError, Depends(_can_replace_invoices)],
    can_update: Annotated[_access.Access | AppError, Depends(_can_update_invoices)],
) -> InvoiceRead:
    # No `roles` on the transition = anyone who may update this record: the entity's update access
    # (roles and row rules) must pass as well as the read access above. Listed roles keep the role check.
    wanted = next((x for x in engine.machine("Invoice")["transitions"] if x["name"] == name and not x["auto"]), None)
    if wanted is not None and not wanted["roles"]:
        if isinstance(can_replace, AppError):
            raise can_replace
        await InvoiceRepository(session, **can_replace.repo_kwargs).get(item_id)
        if isinstance(can_update, AppError):
            raise can_update
        await InvoiceRepository(session, **can_update.repo_kwargs).get(item_id)
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
