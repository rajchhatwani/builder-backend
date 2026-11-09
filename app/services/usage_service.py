"""Usage metering and quotas (B4-5, C23).

`consume` is the one atomic primitive: it either records a granted usage event and raises the
period counter, or refuses with `quota_exceeded` (429) and leaves a REFUSED event behind.

Concurrency: the counter moves with a single-row conditional upsert
    INSERT ... ON CONFLICT (org, metric, period) DO UPDATE SET used = used + :a
    WHERE used + :a <= :limit RETURNING used
Postgres serialises writers on the counter row and re-evaluates the WHERE against the committed
value, so N parallel callers against a quota of L are granted exactly L (never more). The granted
event and the counter move together inside one SAVEPOINT; they commit or roll back with the
caller's transaction (a failed operation is not charged). The refused event is written on its OWN
connection so the refusal stays visible although the caller's request rolls back.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core import metering
from app.exceptions import AppError
from app.models.usage import UsageEvent, UsageLimit

_UPSERT_FREE = text(
    "INSERT INTO usage_counters (organization_id, metric, period_start, used) "
    "VALUES (:o, :m, :p, :a) ON CONFLICT (organization_id, metric, period_start) "
    "DO UPDATE SET used = usage_counters.used + :a RETURNING used"
)
_UPSERT_CAPPED = text(
    "INSERT INTO usage_counters (organization_id, metric, period_start, used) "
    "VALUES (:o, :m, :p, :a) ON CONFLICT (organization_id, metric, period_start) "
    "DO UPDATE SET used = usage_counters.used + :a "
    "WHERE usage_counters.used + :a <= :lim RETURNING used"
)
_READ = text(
    "SELECT used FROM usage_counters WHERE organization_id = :o AND metric = :m AND period_start = :p"
)


class _Refused(Exception):
    """Internal: unwinds the savepoint so no granted event survives a refusal."""


def _unknown(metric: str) -> AppError:
    return AppError("unknown_metric", f"unknown usage metric '{metric}'", 400)


def _now() -> datetime:
    return datetime.now(UTC)


class UsageService:
    def __init__(self, session: AsyncSession, now: datetime | None = None) -> None:
        self.session = session
        self._now = now  # tests pin the clock; production uses the wall clock

    def _clock(self) -> datetime:
        return self._now or _now()

    # -- limits ----------------------------------------------------------------------------
    async def limit_for(self, org_id: uuid.UUID, metric: str) -> int | None:
        if not metering.known(metric):
            raise _unknown(metric)
        row = (
            await self.session.execute(
                select(UsageLimit).where(
                    UsageLimit.organization_id == org_id, UsageLimit.metric == metric
                )
            )
        ).scalar_one_or_none()
        return metering.resolve_limit(
            metric, (row is not None, row.limit_value if row is not None else None)
        )

    async def set_limit(
        self, org_id: uuid.UUID, metric: str, limit_value: int | None, updated_by: uuid.UUID | None
    ) -> None:
        if not metering.known(metric):
            raise _unknown(metric)
        if limit_value is not None and limit_value < 0:
            raise AppError("invalid_limit", "a limit cannot be negative", 422)
        stmt = pg_insert(UsageLimit).values(
            organization_id=org_id, metric=metric, limit_value=limit_value, updated_by=updated_by
        )
        await self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=["organization_id", "metric"],
                set_={"limit_value": limit_value, "updated_by": updated_by},
            )
        )

    # -- consume / release -------------------------------------------------------------------
    async def consume(
        self,
        org_id: uuid.UUID,
        metric: str,
        amount: int = 1,
        *,
        project_id: uuid.UUID | None = None,
        idempotency_key: str | None = None,
    ) -> int:
        """Charge `amount` of `metric` to the org; returns the counter value after the charge.
        Refuses with `quota_exceeded` (429) when it would pass the limit. The same
        `idempotency_key` for the same (org, metric) is charged once; repeats return the
        current counter untouched."""
        mdef = metering.METRICS.get(metric)
        if mdef is None:
            raise _unknown(metric)
        if amount < 1:
            raise AppError("invalid_amount", "amount must be at least 1", 422)
        limit = await self.limit_for(org_id, metric)
        start, end = metering.period_bounds(self._clock(), mdef.period)
        params: dict[str, Any] = {"o": org_id, "m": metric, "p": start, "a": amount}
        used: int | None = None
        duplicate = False
        try:
            async with self.session.begin_nested():
                ev = (
                    pg_insert(UsageEvent)
                    .values(
                        organization_id=org_id,
                        project_id=project_id,
                        metric=metric,
                        amount=amount,
                        outcome="granted",
                        idempotency_key=idempotency_key,
                        created_at=self._clock(),
                        id=uuid.uuid4(),
                    )
                    .on_conflict_do_nothing(
                        index_elements=["organization_id", "metric", "idempotency_key"],
                        index_where=text("idempotency_key IS NOT NULL AND outcome = 'granted'"),
                    )
                    .returning(UsageEvent.id)
                )
                if (await self.session.execute(ev)).first() is None:
                    duplicate = True
                elif limit is not None and amount > limit:
                    raise _Refused
                else:
                    if limit is None:
                        row = (await self.session.execute(_UPSERT_FREE, params)).first()
                    else:
                        row = (
                            await self.session.execute(_UPSERT_CAPPED, {**params, "lim": limit})
                        ).first()
                    if row is None:
                        raise _Refused
                    used = int(row[0])
        except _Refused:
            used = None
        if duplicate:
            return await self._used(org_id, metric, start)
        if used is None:
            current = await self._used(org_id, metric, start)
            await self._record_refused(org_id, project_id, metric, amount)
            raise AppError(
                "quota_exceeded",
                f"the {metric} quota is used up",
                429,
                details=[
                    {
                        "metric": metric,
                        "limit": limit,
                        "used": current,
                        "period_end": end.isoformat() if end else None,
                    }
                ],
            )
        return used

    async def release(self, org_id: uuid.UUID, metric: str, amount: int = 1) -> int:
        """Give back `amount` of a GAUGE metric (workspaces.active); never goes below 0."""
        mdef = metering.METRICS.get(metric)
        if mdef is None:
            raise _unknown(metric)
        if mdef.period != "none":
            raise AppError("not_a_gauge", f"{metric} is a period counter, not a gauge", 400)
        res = await self.session.execute(
            text(
                "UPDATE usage_counters SET used = GREATEST(used - :a, 0) "
                "WHERE organization_id = :o AND metric = :m AND period_start = :p RETURNING used"
            ),
            {"o": org_id, "m": metric, "p": metering.GAUGE_EPOCH, "a": amount},
        )
        row = res.first()
        return int(row[0]) if row else 0

    async def _used(self, org_id: uuid.UUID, metric: str, start: datetime) -> int:
        row = (await self.session.execute(_READ, {"o": org_id, "m": metric, "p": start})).first()
        return int(row[0]) if row else 0

    async def _record_refused(
        self, org_id: uuid.UUID, project_id: uuid.UUID | None, metric: str, amount: int
    ) -> None:
        """Own connection + commit: the refusal must outlive the caller's rolled-back request."""
        bind = self.session.get_bind()
        engine = bind if isinstance(bind, AsyncEngine) else AsyncEngine(bind)  # type: ignore[arg-type]
        async with AsyncSession(engine, expire_on_commit=False) as s:
            s.add(
                UsageEvent(
                    organization_id=org_id,
                    project_id=project_id,
                    metric=metric,
                    amount=amount,
                    outcome="refused",
                    created_at=self._clock(),
                )
            )
            await s.commit()

    # -- reads -----------------------------------------------------------------------------
    async def usage_summary(self, org_id: uuid.UUID) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for name, mdef in metering.METRICS.items():
            start, end = metering.period_bounds(self._clock(), mdef.period)
            refused_q = select(func.count()).select_from(UsageEvent).where(
                UsageEvent.organization_id == org_id,
                UsageEvent.metric == name,
                UsageEvent.outcome == "refused",
            )
            if mdef.period != "none":
                refused_q = refused_q.where(UsageEvent.created_at >= start)
            out.append(
                {
                    "metric": name,
                    "unit": mdef.unit,
                    "period": mdef.period,
                    "period_start": None if mdef.period == "none" else start,
                    "period_end": end,
                    "used": await self._used(org_id, name, start),
                    "limit": await self.limit_for(org_id, name),
                    "refused": int((await self.session.execute(refused_q)).scalar_one()),
                }
            )
        return out

    async def events(
        self, org_id: uuid.UUID, metric: str | None, limit: int, offset: int
    ) -> tuple[list[UsageEvent], int]:
        where = [UsageEvent.organization_id == org_id]
        if metric:
            where.append(UsageEvent.metric == metric)
        total = (
            await self.session.execute(select(func.count()).select_from(UsageEvent).where(*where))
        ).scalar_one()
        rows = (
            await self.session.execute(
                select(UsageEvent)
                .where(*where)
                .order_by(UsageEvent.created_at.desc(), UsageEvent.id)
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
        return list(rows), int(total)


async def consume_import_rows(
    session: AsyncSession,
    org_id: uuid.UUID,
    project_id: uuid.UUID | None,
    n: int,
    *,
    idempotency_key: str | None = None,
) -> None:
    """Hook for the import commit (called by ATLAS, not wired here): charge one batch to
    `imports.batches` and `n` rows to `imports.rows` in the caller's transaction. Call it BEFORE
    writing rows; it raises AppError `quota_exceeded` (429) and the import must then abort. Both
    charges roll back with the caller's transaction. Pass the import batch id as
    `idempotency_key` so a retried commit is not charged twice."""
    svc = UsageService(session)
    key = idempotency_key
    await svc.consume(
        org_id, "imports.batches", 1, project_id=project_id,
        idempotency_key=f"{key}:b" if key else None,
    )  # fmt: skip
    await svc.consume(
        org_id, "imports.rows", n, project_id=project_id,
        idempotency_key=f"{key}:r" if key else None,
    )  # fmt: skip
