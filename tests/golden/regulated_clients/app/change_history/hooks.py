"""Lifecycle hooks that record audited changes (generated).

The hooks only ever look at the fields listed in definitions.HISTORY; any other field is never read,
so it cannot end up in the log. The log rows are added in the write's own transaction (after_save),
so a rolled-back write leaves no history and a committed one always has it."""

import copy
import datetime as _dt
import decimal
import json
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_object_session
from sqlalchemy.orm import object_session

from app.change_history.definitions import HISTORY, MAX_VALUE_BYTES
from app.change_history.models import Change
from app.crud.lifecycle import Hook, HookContext

MARKER = "...[truncated]"
_BEFORE = "_history_before"


def _default(value: Any) -> Any:
    if isinstance(value, decimal.Decimal | uuid.UUID):
        return str(value)
    if isinstance(value, _dt.datetime | _dt.date):
        return value.isoformat()
    return str(value)


def stored(value: Any) -> str | None:
    """The JSON text kept for a value, at most MAX_VALUE_BYTES bytes (longer ones are cut and end in MARKER)."""
    if value is None:
        return None
    text = json.dumps(value, default=_default, ensure_ascii=False)
    raw = text.encode("utf-8", "replace")
    if len(raw) <= MAX_VALUE_BYTES:
        return raw.decode("utf-8")
    keep = MAX_VALUE_BYTES - len(MARKER)
    return raw[:keep].decode("utf-8", "ignore") + MARKER


def merge_hooks(*sets: dict[str, tuple[Hook, ...]]) -> dict[str, tuple[Hook, ...]]:
    """One hooks table out of several blocks' tables: per stage, the hooks run in the order given."""
    merged: dict[str, tuple[Hook, ...]] = {}
    for hooks in sets:
        for stage, funcs in hooks.items():
            merged[stage] = (*merged.get(stage, ()), *funcs)
    return merged


def hooks_for(entity: str) -> dict[str, tuple[Hook, ...]]:
    fields = tuple(HISTORY[entity]["fields"])

    async def remember_before(ctx: HookContext) -> None:
        if ctx.op in ("update", "delete") and ctx.item is not None:
            # Lock the row (same transaction) and re-read it BEFORE taking the snapshot: concurrent
            # updates of one record then run one after another, and every old value is the value the
            # previous change left behind (a gapless chain).
            locker = async_object_session(ctx.item)
            if locker is not None:
                model = type(ctx.item)
                await locker.execute(
                    sa.select(model.id).where(model.id == ctx.item.id).with_for_update()  # type: ignore[attr-defined]
                )
                await locker.refresh(ctx.item, attribute_names=list(fields))
            before = {name: copy.deepcopy(getattr(ctx.item, name, None)) for name in fields}
            setattr(ctx, _BEFORE, before)

    async def record_changes(ctx: HookContext) -> None:
        item = ctx.item
        if item is None or ctx.op not in ("create", "update", "delete"):
            return
        session = object_session(item)
        if session is None:
            return
        before: dict[str, Any] | None = getattr(ctx, _BEFORE, None)
        changes: list[tuple[str, Any, Any]] = []
        if ctx.op == "create":
            changes = [(name, None, getattr(item, name, None)) for name in fields]
        elif before is None:
            return
        elif ctx.op == "delete":
            changes = [(name, before[name], None) for name in fields]
        else:
            for name in fields:
                now = getattr(item, name, None)
                if before[name] != now:  # an update that changes nothing records nothing
                    changes.append((name, before[name], now))
        actor = getattr(ctx.caller, "id", None)
        for name, old, new in changes:
            session.add(
                Change(
                    entity=entity,
                    record_id=item.id,
                    field=name,
                    old_value=stored(old),
                    new_value=stored(new),
                    actor_id=actor,
                    op=ctx.op,
                )
            )

    return {"before_save": (remember_before,), "after_save": (record_changes,)}
