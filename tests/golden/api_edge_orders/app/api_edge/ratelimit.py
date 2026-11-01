"""Token buckets in Postgres (generated).

One atomic INSERT .. ON CONFLICT DO UPDATE refills and takes in a single statement, so it is correct
with any number of API processes. A request takes from every bucket that applies to it (the caller's
and the tenant's) in one transaction: if any is empty nothing is taken. Store errors surface as
`StoreError`; the guard turns them into 503 (writes, and reads unless configured fail-open)."""

import dataclasses
import datetime as dt
import math
from typing import Any

import sqlalchemy as sa

from app.api_edge import definitions
from app.api_edge.caller import Caller
from app.db import session_factory


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)  # tests replace this clock


class StoreError(Exception):
    """The bucket store could not be used."""


@dataclasses.dataclass(frozen=True)
class Limit:
    key: str
    capacity: int
    refill: float


@dataclasses.dataclass(frozen=True)
class Decision:
    allowed: bool
    limit: int  # capacity of the tightest bucket
    remaining: int
    reset_seconds: int  # until that bucket is full again
    retry_after: int  # seconds until the request would be let through (0 when allowed)


_REFILLED = (
    "LEAST(CAST(:cap AS double precision), b.tokens + GREATEST(0, EXTRACT(EPOCH FROM "
    "(CAST(:now AS timestamptz) - b.updated_at))) * CAST(:refill AS double precision))"
)
_TAKE = sa.text(
    f"""
    INSERT INTO api_rate_buckets AS b (bucket_key, tokens, updated_at)
    VALUES (:key, CAST(:cap AS double precision) - CAST(:cost AS double precision),
            CAST(:now AS timestamptz))
    ON CONFLICT (bucket_key) DO UPDATE
    SET tokens = {_REFILLED} - CAST(:cost AS double precision),
        updated_at = GREATEST(b.updated_at, CAST(:now AS timestamptz))
    WHERE {_REFILLED} >= CAST(:cost AS double precision)
    RETURNING tokens
    """
)
_PEEK = sa.text(
    f"SELECT {_REFILLED} FROM api_rate_buckets AS b WHERE b.bucket_key = :key"
)


def _matches(group: dict[str, Any], path: str, method: str) -> bool:
    prefix = group["path_prefix"].rstrip("/")
    under = prefix == "" or path == prefix or path.startswith(prefix + "/")
    return under and (not group["methods"] or method.upper() in group["methods"])


def select_group(path: str, method: str) -> dict[str, Any]:
    """The first route group that matches, else the defaults (cost 1)."""
    cfg = definitions.RATE_LIMITS
    assert cfg is not None
    for group in cfg["groups"]:
        if _matches(group, path, method):
            return {
                "name": group["name"],
                "user": group["user"] or cfg["user"],
                "tenant": group["tenant"] or cfg["tenant"],
                "cost": group["cost"],
            }
    return {"name": "default", "user": cfg["user"], "tenant": cfg["tenant"], "cost": 1}


def limits_for(group: dict[str, Any], caller: Caller) -> list[Limit]:
    cfg = definitions.RATE_LIMITS
    assert cfg is not None
    if not caller.authenticated:
        anon = cfg["anonymous"]
        return [Limit(f"ip:{caller.ip}:{group['name']}", anon["capacity"], anon["refill_per_second"])]
    user, tenant = group["user"], group["tenant"]
    limits = [
        Limit(
            f"u:{caller.tenant_key}:{caller.principal_key}:{group['name']}",
            user["capacity"],
            user["refill_per_second"],
        )
    ]
    if tenant is not None:
        limits.append(
            Limit(f"t:{caller.tenant_key}:{group['name']}", tenant["capacity"], tenant["refill_per_second"])
        )
    return limits


def _seconds(amount: float, refill: float) -> int:
    return max(0, math.ceil(round(amount / refill, 6)))


async def take(limits: list[Limit], cost: int, at: dt.datetime | None = None) -> Decision:
    """Take `cost` tokens from every bucket, or from none."""
    moment = at or now()
    try:
        async with session_factory() as session:
            left: list[tuple[float, Limit]] = []
            for limit in sorted(limits, key=lambda x: x.key):  # one lock order for everybody
                if cost > limit.capacity:
                    return Decision(False, limit.capacity, 0, 0, 0)  # could never succeed
                params: dict[str, Any] = {
                    "key": limit.key,
                    "cap": float(limit.capacity),
                    "refill": limit.refill,
                    "now": moment,
                }
                tokens = (
                    await session.execute(_TAKE, {**params, "cost": float(cost)})
                ).scalar_one_or_none()
                if tokens is None:
                    available = float((await session.execute(_PEEK, params)).scalar_one_or_none() or 0.0)
                    await session.rollback()  # nothing is taken from the buckets before this one
                    return Decision(
                        False,
                        limit.capacity,
                        int(available),
                        _seconds(limit.capacity - available, limit.refill),
                        max(_seconds(cost - available, limit.refill), 1),
                    )
                left.append((float(tokens), limit))
            await session.commit()
    except Exception as exc:
        raise StoreError(type(exc).__name__) from exc
    tokens, tight = min(left, key=lambda pair: pair[0] / pair[1].capacity)
    return Decision(True, tight.capacity, int(tokens), _seconds(tight.capacity - tokens, tight.refill), 0)


async def purge(idle_seconds: int = 86_400) -> int:
    """Delete buckets untouched for a day (a full bucket and a missing one behave alike)."""
    async with session_factory() as session:
        cutoff = now() - dt.timedelta(seconds=idle_seconds)
        result = await session.execute(
            sa.text("DELETE FROM api_rate_buckets WHERE updated_at < :cutoff"), {"cutoff": cutoff}
        )
        await session.commit()
        return int(getattr(result, "rowcount", 0) or 0)
