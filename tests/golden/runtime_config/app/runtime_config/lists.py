"""Lists with a system default set that a tenant can extend and relabel (generated).

The effective list of a tenant is: every system value (possibly relabelled, recoloured, reordered or,
unless locked, switched off by the tenant) plus the values the tenant added. System values are never
removed; deleting a tenant's entry for one puts it back to the default."""

import re
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.runtime_config.definitions import LISTS
from app.runtime_config.models import RcListItem

NIL_TENANT = uuid.UUID(int=0)
VALUE_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")
COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")
# NUL cannot be stored in text columns (it would be a 500); bidi controls can disguise a label.
# Labels are stored verbatim otherwise (HTML included): clients must escape them when rendering.
BAD_TEXT_RE = re.compile("[\\x00\\u202a-\\u202e\\u2066-\\u2069]")
NEW_POSITION = 1000
MAX_POSITION = 100000


async def effective(session: AsyncSession, name: str, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    definition = LISTS[name]
    rows = {
        row.value: row
        for row in (
            await session.execute(
                sa.select(RcListItem).where(
                    RcListItem.tenant_id == tenant_id, RcListItem.list_name == name
                )
            )
        ).scalars()
    }
    items: list[dict[str, Any]] = []
    for index, system in enumerate(definition["items"]):
        row = rows.pop(system["value"], None)
        items.append(
            {
                "value": system["value"],
                "label": row.label if row is not None else system["label"],
                "color": row.color if row is not None else system["color"],
                "position": row.position if row is not None else index * 10,
                "active": row.active if row is not None else True,
                "system": True,
                "locked": system["locked"],
            }
        )
    for row in rows.values():
        items.append(
            {
                "value": row.value,
                "label": row.label,
                "color": row.color,
                "position": row.position,
                "active": row.active,
                "system": False,
                "locked": False,
            }
        )
    return sorted(items, key=lambda i: (i["position"], i["value"]))


async def upsert_item(
    session: AsyncSession,
    name: str,
    value: str,
    tenant_id: uuid.UUID,
    *,
    label: str,
    color: str | None,
    position: int | None,
    active: bool,
) -> None:
    definition = LISTS[name]
    if not VALUE_RE.fullmatch(value):
        raise AppError("invalid_value", "value: lowercase letters, digits and '_' (max 40)", 422)
    if not label.strip() or len(label) > 80:
        raise AppError("invalid_value", "label must be 1 to 80 characters", 422)
    if BAD_TEXT_RE.search(label):
        raise AppError("invalid_value", "label: no NUL or bidi control characters", 422)
    if color is not None and not COLOR_RE.fullmatch(color):
        raise AppError("invalid_value", "color must look like #1a2b3c", 422)
    if position is not None and not 0 <= position <= MAX_POSITION:
        raise AppError("invalid_value", f"position must be 0 to {MAX_POSITION}", 422)
    system = {s["value"]: s for s in definition["items"]}
    if value in system and system[value]["locked"] and not active:
        raise AppError("item_locked", f"{value} cannot be switched off", 422)
    # Two simultaneous additions must not both slip under the limit.
    await session.execute(
        sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtextextended(f"rc_list:{tenant_id}:{name}", 0)))
    )
    mine = set(
        (
            await session.execute(
                sa.select(RcListItem.value).where(
                    RcListItem.tenant_id == tenant_id, RcListItem.list_name == name
                )
            )
        ).scalars()
    )
    if len(set(system) | mine | {value}) > definition["max_items"]:
        raise AppError("list_full", f"list {name} holds at most {definition['max_items']} values", 422)
    if position is None:
        position = (
            list(system).index(value) * 10 if value in system and value not in mine else NEW_POSITION
        )
        if value in mine:
            position = (
                await session.execute(
                    sa.select(RcListItem.position).where(
                        RcListItem.tenant_id == tenant_id,
                        RcListItem.list_name == name,
                        RcListItem.value == value,
                    )
                )
            ).scalar_one()
    stmt = pg_insert(RcListItem).values(
        tenant_id=tenant_id,
        list_name=name,
        value=value,
        label=label,
        color=color,
        position=position,
        active=active,
        updated_at=sa.func.now(),
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["tenant_id", "list_name", "value"],
            set_={
                "label": stmt.excluded.label,
                "color": stmt.excluded.color,
                "position": stmt.excluded.position,
                "active": stmt.excluded.active,
                "updated_at": stmt.excluded.updated_at,
            },
        )
    )


async def remove_item(session: AsyncSession, name: str, value: str, tenant_id: uuid.UUID) -> bool:
    """Deletes the tenant's entry (a custom value goes away, a system value returns to its default)."""
    result = await session.execute(
        sa.delete(RcListItem).where(
            RcListItem.tenant_id == tenant_id,
            RcListItem.list_name == name,
            RcListItem.value == value,
        )
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]
