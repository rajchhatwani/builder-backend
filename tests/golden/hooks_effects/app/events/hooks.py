"""Lifecycle hooks that write an entity's events (generated).

The outbox row is added in the write's own transaction (stage after_save), so a rolled-back write
leaves no event and a committed one always has its event, even if the process dies right after the
commit. An error here rolls the write back (fail closed). Only the fields listed in
definitions.ENTITIES are ever read, so nothing else can reach an event."""

import copy
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_object_session

from app.core.errors import NotFoundError
from app.crud.lifecycle import Hook, HookContext
from app.events import definitions, outbox
from app.events.types import EVENT_TYPES

_BEFORE = "_events_before"


def _snapshot(item: Any, names: tuple[str, ...]) -> dict[str, Any]:
    return {name: copy.deepcopy(getattr(item, name)) for name in names}


def _tenant(entity: str, item: Any) -> Any:
    return getattr(item, "tenant_id", None) if definitions.ENTITIES[entity]["tenant"] else None


async def _lock_alive(item: Any, names: tuple[str, ...]) -> None:
    """Lock the row about to be deleted, and refuse when a concurrent delete already got it.

    The delete path loads the row without a lock, so N concurrent deletes of one id all find it and
    each would write a `.deleted` event. `SELECT ... FOR UPDATE` serialises them: the loser waits,
    then (READ COMMITTED re-checks the predicate) finds the row gone or soft-deleted and stops
    here, before any event is written. The snapshot is re-read under the lock."""
    session = async_object_session(item)
    if session is None:
        raise RuntimeError("cannot write the event: the record is not in a session")
    model = type(item)
    conditions = [model.id == item.id]
    if hasattr(model, "deleted_at"):
        conditions.append(model.deleted_at.is_(None))
    locked = (await session.execute(sa.select(model.id).where(*conditions).with_for_update())).first()
    if locked is None:
        raise NotFoundError(f"{model.__name__} {item.id} not found")
    await session.refresh(item, attribute_names=list(names))


def hooks_for(entity: str) -> dict[str, tuple[Hook, ...]]:
    cfg = definitions.ENTITIES[entity]
    names: tuple[str, ...] = tuple(cfg["fields"])
    prefix: str = cfg["event"]

    async def remember(ctx: HookContext) -> None:
        if ctx.op == "delete" and ctx.item is not None:
            await _lock_alive(ctx.item, names)
        if ctx.op in ("update", "delete") and ctx.item is not None:
            setattr(ctx, _BEFORE, (_snapshot(ctx.item, names), _tenant(entity, ctx.item)))

    async def record(ctx: HookContext) -> None:
        if ctx.op not in ("create", "update", "delete"):
            return  # a transition is announced by `<entity>.transitioned` (see below)
        item = ctx.item
        session = async_object_session(item) if item is not None else None
        if item is None or session is None:
            raise RuntimeError("cannot write the event: the record is not in a session")
        if ctx.op == "delete":
            before = getattr(ctx, _BEFORE, None)
            if before is None:
                raise RuntimeError("cannot write the event: no snapshot of the deleted record")
            data, tenant = before
            payload = EVENT_TYPES[f"{prefix}.deleted"](data=data)
            await outbox.add_event(session, f"{prefix}.deleted", entity, item.id, payload, tenant)
            return
        # Settle first (automatic transitions are applied in memory), then read the stored values.
        await session.flush()
        await session.refresh(item, attribute_names=list(names))
        data = _snapshot(item, names)
        tenant = _tenant(entity, item)
        if ctx.op == "create":
            payload = EVENT_TYPES[f"{prefix}.created"](data=data)
            await outbox.add_event(session, f"{prefix}.created", entity, item.id, payload, tenant)
            return
        before_state = getattr(ctx, _BEFORE, None)
        if before_state is None:
            raise RuntimeError("cannot write the event: no snapshot of the record before the change")
        old = before_state[0]
        changed = [n for n in names if n != "updated_at" and old[n] != data[n]]
        if not changed:
            return  # an update that changes nothing announces nothing
        payload = EVENT_TYPES[f"{prefix}.updated"](data=data, changed=changed)
        await outbox.add_event(session, f"{prefix}.updated", entity, item.id, payload, tenant)

    return {"before_save": (remember,), "after_save": (record,)}


def attach(entity: str, existing: dict[str, tuple[Hook, ...]]) -> dict[str, tuple[Hook, ...]]:
    """The entity's hooks with the event hooks added LAST in each stage."""
    merged = dict(existing)
    for stage, funcs in hooks_for(entity).items():
        merged[stage] = (*merged.get(stage, ()), *funcs)
    return merged
