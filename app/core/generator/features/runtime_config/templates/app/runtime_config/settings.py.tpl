"""Typed settings that a role can change at run time (generated).

A value is checked against its definition (type, range, length) before it is stored; a value that
does not fit is refused with 422 and nothing changes. Settings hold business knobs, not secrets."""

import datetime as _dt
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.runtime_config.definitions import SETTINGS
from app.runtime_config.models import RcSetting

NIL_TENANT = uuid.UUID(int=0)
MAX_INT = 2**53
_DECIMAL = re.compile(r"-?[0-9]{1,18}(\.[0-9]{1,8})?")


def _bad(key: str, why: str) -> AppError:
    return AppError("invalid_value", f"setting {key}: {why}", 422)


def _decimal(raw: object) -> Decimal | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return Decimal(raw)
    if isinstance(raw, str) and _DECIMAL.fullmatch(raw):
        try:
            return Decimal(raw)
        except InvalidOperation:
            return None
    return None


def check_value(key: str, raw: object) -> object:
    """The value as it is stored (JSON-able), or a 422 saying what is wrong."""
    d = SETTINGS[key]
    kind = d["type"]
    if kind == "string":
        if not isinstance(raw, str):
            raise _bad(key, "must be a string")
        if len(raw) > d["max_length"]:
            raise _bad(key, f"at most {d['max_length']} characters")
        if "\x00" in raw:
            raise _bad(key, "NUL characters are not allowed")
        return raw
    if kind == "bool":
        if not isinstance(raw, bool):
            raise _bad(key, "must be true or false")
        return raw
    if kind == "int":
        if isinstance(raw, bool) or not isinstance(raw, int) or abs(raw) > MAX_INT:
            raise _bad(key, "must be a whole number")
        number = Decimal(raw)
    else:
        parsed = _decimal(raw)
        if parsed is None:
            raise _bad(key, 'must be a decimal written as a string, like "12.50"')
        number = parsed
    if d["minimum"] is not None and number < Decimal(str(d["minimum"])):
        raise _bad(key, f"must be at least {d['minimum']}")
    if d["maximum"] is not None and number > Decimal(str(d["maximum"])):
        raise _bad(key, f"must be at most {d['maximum']}")
    return raw if kind == "int" else format(number, "f")


def typed(key: str, stored: object) -> Any:
    """A stored value as Python: decimals become `Decimal`."""
    return Decimal(str(stored)) if SETTINGS[key]["type"] == "decimal" else stored


async def stored_values(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, RcSetting]:
    rows = (
        await session.execute(sa.select(RcSetting).where(RcSetting.tenant_id == tenant_id))
    ).scalars()
    return {row.key: row for row in rows if row.key in SETTINGS}


async def get_setting(session: AsyncSession, key: str, tenant_id: uuid.UUID | None = None) -> Any:
    """The effective value for the tenant (its saved value, else the default)."""
    if key not in SETTINGS:
        raise ValueError(f"no setting named {key!r}")
    row = await session.get(RcSetting, (tenant_id or NIL_TENANT, key))
    return typed(key, row.value if row is not None else SETTINGS[key]["default"])


async def set_setting(
    session: AsyncSession,
    key: str,
    raw: object,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID | None,
) -> None:
    value = check_value(key, raw)
    stmt = pg_insert(RcSetting).values(
        tenant_id=tenant_id,
        key=key,
        value=value,
        updated_by=actor_id,
        updated_at=_dt.datetime.now(_dt.UTC),
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["tenant_id", "key"],
            set_={"value": stmt.excluded.value, "updated_by": actor_id, "updated_at": stmt.excluded.updated_at},
        )
    )


async def reset_setting(session: AsyncSession, key: str, tenant_id: uuid.UUID) -> None:
    await session.execute(
        sa.delete(RcSetting).where(RcSetting.tenant_id == tenant_id, RcSetting.key == key)
    )
