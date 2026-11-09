"""Transition routes for entities with a state machine (generated)."""

import datetime as _dt
import uuid as _uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import access as _access
from app.auth import field_access as _fx
from app.auth.deps import CurrentUser
from app.auth.service import effective_roles
from app.core.errors import AppError
from app.crud.expenses import ExpenseRepository
from app.db import SessionDep
from app.routers.expenses import _ACCESS as _ACCESS_expenses
from app.schemas.expenses import ExpenseRead
from app.state_machines import engine

router = APIRouter(tags=["state machines"])


class TransitionInfo(BaseModel):
    name: str
    to_state: str
    allowed: bool
    refused_because: str | None = None  # "role", "guard", or "unavailable" (guard hidden from this caller)


class StateChange(BaseModel):
    model_config = {"from_attributes": True}

    transition: str
    from_state: str | None
    to_state: str
    actor_id: _uuid.UUID | None
    automatic: bool
    created_at: _dt.datetime
_access_expenses = _ACCESS_expenses["get"]


async def _can_replace_expenses(user: CurrentUser) -> _access.Access | AppError:
    """The entity's own replace access for this caller; a refusal is kept, not raised: only a transition
    with no `roles` needs it."""
    try:
        return await _ACCESS_expenses["replace"](user)
    except AppError as refused:
        return refused


async def _can_update_expenses(user: CurrentUser) -> _access.Access | AppError:
    """The entity's own update access for this caller; a refusal is kept, not raised: only a transition
    with no `roles` needs it."""
    try:
        return await _ACCESS_expenses["update"](user)
    except AppError as refused:
        return refused


def _roles_expenses(access: _access.Access) -> set[str]:
    return effective_roles(access.user.roles) if access.user is not None else set()


@router.get("/expenses/{item_id}/transitions", response_model=list[TransitionInfo])
async def list_expenses_transitions(
    item_id: _uuid.UUID,
    session: SessionDep,
    access: Annotated[_access.Access, Depends(_access_expenses)],
) -> list[dict[str, object]]:
    item = await ExpenseRepository(session, **access.repo_kwargs).get(item_id)
    return engine.available(
        "Expense",
        item,
        _roles_expenses(access),
        mask_guard=bool(_fx.hidden_read("Expense", access.user)),
    )


@router.post("/expenses/{item_id}/transitions/{name}", response_model=ExpenseRead, response_model_exclude_unset=True)
async def apply_expenses_transition(
    item_id: _uuid.UUID,
    name: str,
    session: SessionDep,
    access: Annotated[_access.Access, Depends(_access_expenses)],
    can_replace: Annotated[_access.Access | AppError, Depends(_can_replace_expenses)],
    can_update: Annotated[_access.Access | AppError, Depends(_can_update_expenses)],
) -> ExpenseRead:
    # No `roles` on the transition = anyone who may update this record: the entity's update access
    # (roles and row rules) must pass as well as the read access above. Listed roles keep the role check.
    wanted = next((x for x in engine.machine("Expense")["transitions"] if x["name"] == name and not x["auto"]), None)
    if wanted is not None and not wanted["roles"]:
        if isinstance(can_replace, AppError):
            raise can_replace
        await ExpenseRepository(session, **can_replace.repo_kwargs).get(item_id)
        if isinstance(can_update, AppError):
            raise can_update
        await ExpenseRepository(session, **can_update.repo_kwargs).get(item_id)
    repo = ExpenseRepository(session, **access.repo_kwargs)
    item = await engine.apply(
        repo,
        "Expense",
        item_id,
        name,
        roles=_roles_expenses(access),
        actor_id=access.user.id if access.user is not None else None,
        mask_guard=bool(_fx.hidden_read("Expense", access.user)),
    )
    return _fx.shape("Expense", access.user, ExpenseRead.model_validate(item))


@router.get("/expenses/{item_id}/state-history", response_model=list[StateChange])
async def expenses_state_history(
    item_id: _uuid.UUID,
    session: SessionDep,
    access: Annotated[_access.Access, Depends(_access_expenses)],
) -> list[StateChange]:
    await ExpenseRepository(session, **access.repo_kwargs).get(item_id)
    rows = await engine.history(session, "Expense", item_id)
    return [StateChange.model_validate(row) for row in rows]
