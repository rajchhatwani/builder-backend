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
from app.crud.orders import OrderRepository
from app.db import SessionDep
from app.routers.orders import _ACCESS as _ACCESS_orders
from app.schemas.orders import OrderRead
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
_access_orders = _ACCESS_orders["get"]


async def _can_replace_orders(user: CurrentUser) -> _access.Access | AppError:
    """The entity's own replace access for this caller; a refusal is kept, not raised: only a transition
    with no `roles` needs it."""
    try:
        return await _ACCESS_orders["replace"](user)
    except AppError as refused:
        return refused


async def _can_update_orders(user: CurrentUser) -> _access.Access | AppError:
    """The entity's own update access for this caller; a refusal is kept, not raised: only a transition
    with no `roles` needs it."""
    try:
        return await _ACCESS_orders["update"](user)
    except AppError as refused:
        return refused


def _roles_orders(access: _access.Access) -> set[str]:
    return effective_roles(access.user.roles) if access.user is not None else set()


@router.get("/orders/{item_id}/transitions", response_model=list[TransitionInfo])
async def list_orders_transitions(
    item_id: _uuid.UUID,
    session: SessionDep,
    access: Annotated[_access.Access, Depends(_access_orders)],
) -> list[dict[str, object]]:
    item = await OrderRepository(session, **access.repo_kwargs).get(item_id)
    await engine.prime_settings(session, item)
    return engine.available("Order", item, _roles_orders(access))


@router.post("/orders/{item_id}/transitions/{name}", response_model=OrderRead)
async def apply_orders_transition(
    item_id: _uuid.UUID,
    name: str,
    session: SessionDep,
    access: Annotated[_access.Access, Depends(_access_orders)],
    can_replace: Annotated[_access.Access | AppError, Depends(_can_replace_orders)],
    can_update: Annotated[_access.Access | AppError, Depends(_can_update_orders)],
) -> OrderRead:
    # No `roles` on the transition = anyone who may update this record: the entity's update access
    # (roles and row rules) must pass as well as the read access above. Listed roles keep the role check.
    wanted = next((x for x in engine.machine("Order")["transitions"] if x["name"] == name and not x["auto"]), None)
    if wanted is not None and not wanted["roles"]:
        if isinstance(can_replace, AppError):
            raise can_replace
        await OrderRepository(session, **can_replace.repo_kwargs).get(item_id)
        if isinstance(can_update, AppError):
            raise can_update
        await OrderRepository(session, **can_update.repo_kwargs).get(item_id)
    repo = OrderRepository(session, **access.repo_kwargs)
    item = await engine.apply(
        repo,
        "Order",
        item_id,
        name,
        roles=_roles_orders(access),
        actor_id=access.user.id if access.user is not None else None,
    )
    return OrderRead.model_validate(item)


@router.get("/orders/{item_id}/state-history", response_model=list[StateChange])
async def orders_state_history(
    item_id: _uuid.UUID,
    session: SessionDep,
    access: Annotated[_access.Access, Depends(_access_orders)],
) -> list[StateChange]:
    await OrderRepository(session, **access.repo_kwargs).get(item_id)
    rows = await engine.history(session, "Order", item_id)
    return [StateChange.model_validate(row) for row in rows]
