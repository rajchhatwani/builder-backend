"""State machines at run time (generated).

* A record's state is only ever changed here: the create and update schemas have no state field.
* A transition needs: the record is in one of its `from` states, the caller holds one of its roles
  (when it lists any), and its guard (an expression over the record's own fields) is true. A guard
  that is null, errors or overflows counts as false: the move is refused.
* An automatic transition is applied right after a write (inside the same database transaction)
  whenever its guard holds; the platform's moves have no actor.
* Every state a record enters is logged in `state_transitions`.
"""

import uuid
from collections.abc import Callable
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.state_machines.definitions import MACHINES
from app.state_machines.expr.pyeval import compile_python
from app.state_machines.models import StateTransition

MAX_AUTO_STEPS = 20

Guard = Callable[[dict[str, Any]], Any]
_GUARDS: dict[tuple[str, str], Guard] = {
    (entity, t["name"]): compile_python(t["guard"])
    for entity, machine in MACHINES.items()
    for t in machine["transitions"]
    if t["guard"] is not None
}


def machine(entity: str) -> dict[str, Any]:
    return MACHINES[entity]  # type: ignore[no-any-return]


def row_values(item: Any) -> dict[str, Any]:
    return {c.key: getattr(item, c.key, None) for c in sa.inspect(type(item)).column_attrs}


def guard_holds(entity: str, transition: dict[str, Any], values: dict[str, Any]) -> bool:
    guard = _GUARDS.get((entity, transition["name"]))
    if guard is None:
        return True
    try:
        return guard(values) is True
    except Exception:
        return False  # fail closed


def current_state(entity: str, item: Any) -> str:
    return str(getattr(item, machine(entity)["field"]))


def log_state(
    session: AsyncSession,
    entity: str,
    item: Any,
    transition: str,
    from_state: str | None,
    to_state: str,
    actor_id: uuid.UUID | None,
    *,
    automatic: bool,
) -> None:
    session.add(
        StateTransition(
            entity=entity,
            record_id=item.id,
            transition=transition,
            from_state=from_state,
            to_state=to_state,
            actor_id=actor_id,
            automatic=automatic,
        )
    )


def settle(session: AsyncSession, entity: str, item: Any) -> None:
    """Apply automatic transitions, one after another, until none applies."""
    m = machine(entity)
    for _ in range(MAX_AUTO_STEPS):
        state = current_state(entity, item)
        values = row_values(item)
        step = next(
            (
                t
                for t in m["transitions"]
                if t["auto"] and state in t["from"] and guard_holds(entity, t, values)
            ),
            None,
        )
        if step is None:
            return
        setattr(item, m["field"], step["to"])
        log_state(session, entity, item, step["name"], state, step["to"], None, automatic=True)
    raise AppError("state_loop", "automatic transitions did not settle", 500)


def available(entity: str, item: Any, roles: set[str]) -> list[dict[str, Any]]:
    """The manual transitions out of the record's current state, and whether the caller may use each."""
    m = machine(entity)
    state = current_state(entity, item)
    values = row_values(item)
    out = []
    for t in m["transitions"]:
        if t["auto"] or state not in t["from"]:
            continue
        reason = None
        if t["roles"] and not roles & set(t["roles"]):
            reason = "role"
        elif not guard_holds(entity, t, values):
            reason = "guard"
        out.append(
            {"name": t["name"], "to_state": t["to"], "allowed": reason is None, "refused_because": reason}
        )
    return out


async def apply(
    repo: Any,
    entity: str,
    item_id: uuid.UUID,
    name: str,
    *,
    roles: set[str],
    actor_id: uuid.UUID | None,
) -> Any:
    """Move one record through a manual transition. `repo` finds the record under the caller's access
    rules; the row is then locked so two simultaneous moves cannot both start from the same state."""
    m = machine(entity)
    t = next((x for x in m["transitions"] if x["name"] == name and not x["auto"]), None)
    if t is None:
        raise NotFoundError(f"{entity} has no transition named {name!r}")
    await repo.get(item_id)  # not found / not allowed to see it
    # The caller's role is checked before the record's state: someone who may not use this transition
    # learns nothing about the state (403, never 409).
    if t["roles"] and not roles & set(t["roles"]):
        raise AppError("forbidden", "you do not have permission to do that", 403)
    session: AsyncSession = repo.session
    locked = await session.execute(
        sa.select(repo.model)
        .where(repo.model.id == item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    item = locked.scalar_one()
    state = current_state(entity, item)
    if state not in t["from"]:
        raise AppError(
            "invalid_transition", f"{name} cannot start from the state {state!r}", 409
        )
    if not guard_holds(entity, t, row_values(item)):
        await session.rollback()
        raise AppError("transition_refused", f"the conditions for {name} are not met", 409)
    setattr(item, m["field"], t["to"])
    log_state(session, entity, item, name, state, t["to"], actor_id, automatic=False)
    ctx = repo._ctx("transition", {})
    ctx.item = item
    await repo._flush()
    await repo._finish(ctx)  # after_save (automatic moves), commit, after_commit
    return await repo.get(item_id, policy=False)


async def history(session: AsyncSession, entity: str, item_id: uuid.UUID) -> list[StateTransition]:
    rows = await session.execute(
        sa.select(StateTransition)
        .where(StateTransition.entity == entity, StateTransition.record_id == item_id)
        .order_by(StateTransition.created_at, StateTransition.id)
    )
    return list(rows.scalars())
