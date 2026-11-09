"""Lifecycle hooks that tie the state machines into every write (generated)."""

from sqlalchemy.orm import object_session

from app.core.errors import AppError
from app.crud.lifecycle import Hook, HookContext
from app.state_machines import engine


def hooks_for(entity: str) -> dict[str, tuple[Hook, ...]]:
    m = engine.machine(entity)
    field = m["field"]

    async def set_initial_state(ctx: HookContext) -> None:
        if ctx.op == "create":
            ctx.values[field] = m["initial"]  # whatever the caller sent
        elif field in ctx.values:
            raise AppError("state_is_managed", f"{field} changes only through transitions", 422)

    async def settle_and_log(ctx: HookContext) -> None:
        item = ctx.item
        if item is None or ctx.op == "delete":
            return
        session = object_session(item)
        if session is None:
            return
        if ctx.op == "create":
            state = engine.current_state(entity, item)
            engine.log_state(
                session, entity, item, "created", None, state, getattr(ctx.caller, "id", None),
                automatic=False,
            )
        engine.settle(session, entity, item)

    return {"before_save": (set_initial_state,), "after_save": (settle_and_log,)}
