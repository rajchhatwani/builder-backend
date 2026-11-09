"""Writes the realtime event in the write's own transaction (stage after_save): a rolled-back write leaves no
event, a committed one always has its event. An error here rolls the write back (fail closed). Only the
record id, the entity and the operation are read: no field value can reach the log."""

from typing import Any

from sqlalchemy.ext.asyncio import async_object_session

from app.crud.lifecycle import Hook, HookContext
from app.realtime import service

_OPS = {"create": "created", "update": "updated", "replace": "updated", "transition": "updated", "delete": "deleted"}


def hooks_for(entity: str) -> dict[str, tuple[Hook, ...]]:
    async def publish(ctx: HookContext) -> None:
        item: Any = ctx.item
        op = _OPS.get(ctx.op)
        if item is None or op is None:
            return
        session = async_object_session(item)
        if session is None:
            raise RuntimeError("cannot write the realtime event: the record is not in a session")
        await service.publish(
            session,
            entity,
            item.id,
            op,
            tenant_id=getattr(item, "tenant_id", None),
            created_by_id=getattr(item, "created_by_id", None),
        )

    return {"after_save": (publish,)}


def attach(entity: str, existing: dict[str, tuple[Hook, ...]]) -> dict[str, tuple[Hook, ...]]:
    """Add this hook after the hooks already registered (the event outbox, history, your own)."""
    merged = dict(existing)
    for stage, funcs in hooks_for(entity).items():
        merged[stage] = (*merged.get(stage, ()), *funcs)
    return merged
