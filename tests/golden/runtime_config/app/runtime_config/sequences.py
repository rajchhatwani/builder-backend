"""Gapless sequences (generated).

`next_number` takes the next number INSIDE THE CALLER'S TRANSACTION: it locks the counter row
(SELECT ... FOR UPDATE), reads it and moves it on. Another caller wanting the same counter waits until
this transaction ends; if this one rolls back, the counter never moved, so no number is burned. The
caller must keep the number in the same transaction (insert the record that carries it, then commit).
Never call it from a separate session or an autocommit connection: that would defeat the guarantee.
"""

import datetime as _dt
import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.runtime_config.definitions import SEQUENCES
from app.runtime_config.models import RcSequence

NIL_TENANT = uuid.UUID(int=0)


def _definition(name: str) -> dict[str, object]:
    try:
        return SEQUENCES[name]  # type: ignore[no-any-return]
    except KeyError:
        raise ValueError(f"no sequence named {name!r}") from None


def _scope(
    name: str, tenant_id: uuid.UUID | None, now: _dt.datetime | None
) -> tuple[dict[str, object], uuid.UUID, int]:
    definition = _definition(name)
    if definition["per_tenant"]:
        if tenant_id is None:
            raise ValueError(f"sequence {name!r} counts per tenant: pass tenant_id")
        tenant = tenant_id
    else:
        tenant = NIL_TENANT
    year = (now or _dt.datetime.now(_dt.UTC)).year
    return definition, tenant, year if definition["reset_yearly"] else 0


def format_number(definition: dict[str, object], value: int, period: int) -> str:
    year = f"{period}-" if period else ""
    return f"{definition['prefix']}{year}{str(value).zfill(int(definition['padding']))}"  # type: ignore[call-overload]


async def next_number(
    session: AsyncSession,
    name: str,
    *,
    tenant_id: uuid.UUID | None = None,
    now: _dt.datetime | None = None,
) -> str:
    """The next formatted number of sequence `name`; commits only with the caller's transaction."""
    definition, tenant, period = _scope(name, tenant_id, now)
    start = int(definition["start"])  # type: ignore[call-overload]
    # Creates the counter row on first use (inside this transaction: a rollback removes it again).
    await session.execute(
        pg_insert(RcSequence)
        .values(name=name, tenant_id=tenant, period=period, next_value=start)
        .on_conflict_do_nothing(index_elements=["name", "tenant_id", "period"])
    )
    where = (
        RcSequence.name == name,
        RcSequence.tenant_id == tenant,
        RcSequence.period == period,
    )
    taken = (
        await session.execute(sa.select(RcSequence.next_value).where(*where).with_for_update())
    ).scalar_one()
    await session.execute(sa.update(RcSequence).where(*where).values(next_value=taken + 1))
    return format_number(definition, taken, period)


async def peek(
    session: AsyncSession,
    name: str,
    *,
    tenant_id: uuid.UUID | None = None,
    now: _dt.datetime | None = None,
) -> str:
    """What the next caller would get, without taking it (no lock: informational only)."""
    definition, tenant, period = _scope(name, tenant_id, now)
    current = (
        await session.execute(
            sa.select(RcSequence.next_value).where(
                RcSequence.name == name,
                RcSequence.tenant_id == tenant,
                RcSequence.period == period,
            )
        )
    ).scalar_one_or_none()
    return format_number(definition, int(definition["start"]) if current is None else current, period)  # type: ignore[call-overload]
