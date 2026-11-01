"""Cron schedules (generated): each tick of each schedule enqueues exactly one job.

Every worker process runs `run_scheduler` (JOBS_SCHEDULER_ENABLED=false turns it off), and any number of them
may be up at once. Nothing elects a leader: a tick is claimed by inserting (schedule, fire_time) into
jb_schedule_fires, whose primary key admits one insert; the process that wins it enqueues the job in the
same transaction, the others see a conflict and do nothing. If the process dies before commit, nothing
happened and the next one fires the tick.

Missed ticks: only the most recent tick at or before now is ever considered, so a long outage costs at
most ONE catch-up run (`missed: catch_up_one`), or none (`missed: skip`, when the tick is older than
JOBS_SCHEDULER_GRACE_SECONDS). A schedule seen for the first time starts from now: it never replays the past.
"""

import asyncio
import contextlib
import datetime as _dt
from functools import cache
from zoneinfo import ZoneInfo

import sqlalchemy as sa
import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.jobs import config, cron, definitions, queue
from app.jobs.models import Schedule, ScheduleFire
from app.models._base import utcnow

logger = structlog.get_logger()

SessionFactory = async_sessionmaker[AsyncSession]


@cache
def _compiled(expression: str) -> cron.CronSpec:
    return cron.parse(expression)


@cache
def _zone(name: str) -> ZoneInfo:
    return cron.zone(name)


async def _fire_one(factory: SessionFactory, name: str, now: _dt.datetime) -> _dt.datetime | None:
    cfg = definitions.SCHEDULES[name]
    async with factory() as session:
        await session.execute(
            pg_insert(Schedule).values(name=name, baseline_at=now).on_conflict_do_nothing()
        )
        baseline = (await session.execute(sa.select(Schedule.baseline_at).where(Schedule.name == name))).scalar_one()
        last = (
            await session.execute(
                sa.select(sa.func.max(ScheduleFire.fire_time)).where(ScheduleFire.schedule == name)
            )
        ).scalar_one()
        floor = baseline if last is None else max(baseline, last)
        tick = cron.previous_fire(_compiled(cfg["cron"]), _zone(cfg["timezone"]), now)
        if tick is None or tick <= floor:
            await session.commit()  # keeps the baseline
            return None
        late = (now - tick).total_seconds()
        outcome = "skipped" if cfg["missed"] == "skip" and late > config.scheduler_grace() else "enqueued"
        won = (
            await session.execute(
                pg_insert(ScheduleFire)
                .values(schedule=name, fire_time=tick, outcome=outcome, created_at=now)
                .on_conflict_do_nothing()
                .returning(ScheduleFire.schedule)
            )
        ).first()
        if won is None:  # another scheduler took this tick
            await session.commit()
            return None
        if outcome == "enqueued":
            job_id = await queue.enqueue(
                cfg["job"],
                {"schedule": name, "fire_time": tick.isoformat()},
                session=session,
                now=now,
                dedupe_key=f"schedule:{name}:{tick.isoformat()}",
            )
            await session.execute(
                sa.update(ScheduleFire)
                .where(ScheduleFire.schedule == name, ScheduleFire.fire_time == tick)
                .values(job_id=job_id)
            )
        await session.commit()
    logger.info("schedule_fired", schedule=name, fire_time=tick.isoformat(), outcome=outcome)
    return tick if outcome == "enqueued" else None


async def fire_due(factory: SessionFactory, now: _dt.datetime | None = None) -> list[tuple[str, _dt.datetime]]:
    """Fire every schedule whose tick is due at `now`. Safe to call from many processes at once.
    Returns (schedule, tick) for the ticks THIS call enqueued."""
    stamp = now or utcnow()
    fired: list[tuple[str, _dt.datetime]] = []
    for name, cfg in sorted(definitions.SCHEDULES.items()):
        if not cfg["enabled"]:
            continue
        tick = await _fire_one(factory, name, stamp)
        if tick is not None:
            fired.append((name, tick))
    return fired


async def run_scheduler(factory: SessionFactory, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await fire_due(factory)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # the database may be briefly away: log the class, try again
            logger.error("scheduler_error", error=type(exc).__name__)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), config.scheduler_tick())
