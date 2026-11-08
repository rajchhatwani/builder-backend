"""Per-tenant quotas with a hard cap (generated).

A meter counts per tenant and period (UTC day or month). One atomic INSERT .. ON CONFLICT DO UPDATE ..
WHERE used + cost <= limit adds to the counter only while it fits. Several matching meters are
charged in one transaction: if one is full none is charged. Store errors surface as `StoreError`."""

import dataclasses
import datetime as dt
from typing import Any

import sqlalchemy as sa

from app.api_edge import definitions
from app.db import session_factory


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)  # tests replace this clock


class StoreError(Exception):
    """The quota store could not be used."""


@dataclasses.dataclass(frozen=True)
class Exceeded:
    meter: str
    limit: int
    used: int
    retry_after: int  # seconds until the period ends


_CHARGE = sa.text(
    """
    INSERT INTO api_quota_usage AS q (tenant_key, meter, period_start, used)
    VALUES (:tenant, :meter, :period, :cost)
    ON CONFLICT (tenant_key, meter, period_start) DO UPDATE SET used = q.used + :cost
    WHERE q.used + :cost <= :limit
    RETURNING used
    """
)
_USED = sa.text(
    "SELECT used FROM api_quota_usage WHERE tenant_key = :tenant AND meter = :meter AND period_start = :period"
)


def period_start(period: str, at: dt.datetime) -> dt.date:
    day = at.astimezone(dt.UTC).date()
    return day if period == "day" else day.replace(day=1)


def period_end(period: str, at: dt.datetime) -> dt.datetime:
    start = period_start(period, at)
    if period == "day":
        end = start + dt.timedelta(days=1)
    else:
        end = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return dt.datetime(end.year, end.month, end.day, tzinfo=dt.UTC)


def matching(path: str, method: str) -> list[dict[str, Any]]:
    out = []
    for quota in definitions.QUOTAS:
        prefix = quota["path_prefix"].rstrip("/")
        under = prefix == "" or path == prefix or path.startswith(prefix + "/")
        if under and (not quota["methods"] or method.upper() in quota["methods"]):
            out.append(quota)
    return sorted(out, key=lambda q: q["meter"])


async def charge(
    tenant_key: str, quotas: list[dict[str, Any]], at: dt.datetime | None = None
) -> Exceeded | None:
    """Add each quota's cost to the tenant's counters, or to none. None = charged."""
    moment = at or now()
    try:
        async with session_factory() as session:
            for quota in quotas:
                where = {
                    "tenant": tenant_key,
                    "meter": quota["meter"],
                    "period": period_start(quota["period"], moment),
                }
                if quota["cost"] > quota["limit"]:
                    return Exceeded(quota["meter"], quota["limit"], 0, 1)
                used = (
                    await session.execute(_CHARGE, {**where, "cost": quota["cost"], "limit": quota["limit"]})
                ).scalar_one_or_none()
                if used is None:
                    current = (await session.execute(_USED, where)).scalar_one_or_none() or 0
                    await session.rollback()
                    wait = int((period_end(quota["period"], moment) - moment).total_seconds()) + 1
                    return Exceeded(quota["meter"], quota["limit"], int(current), wait)
            await session.commit()
    except Exception as exc:
        raise StoreError(type(exc).__name__) from exc
    return None


async def purge(keep_days: int = 400) -> int:
    async with session_factory() as session:
        cutoff = now().date() - dt.timedelta(days=keep_days)
        result = await session.execute(
            sa.text("DELETE FROM api_quota_usage WHERE period_start < :cutoff"), {"cutoff": cutoff}
        )
        await session.commit()
        return int(getattr(result, "rowcount", 0) or 0)
