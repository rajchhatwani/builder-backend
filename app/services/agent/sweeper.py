"""Crash-resume sweeper (B-003): re-drive agent runs whose driver died.

A run that is mid-flight (planning/running/gating/applying) but whose lease has expired has no
driver. The sweeper takes the lease with the same compare-and-set a manual resume uses, so a live
driver is never disturbed, and drives the run on from its persisted steps. It runs once at start
and then every `agent_sweep_interval_seconds` (started from the app lifespan).
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.exceptions import AppError
from app.models.agent import AiApproval, AiRun, AiStep
from app.models.project import Project
from app.services.behavior_service import system_actor
from app.services.agent.run_service import AgentDeps, RunDriver, get_agent_deps
from app.services.ai.gateway import ModelGateway

log = logging.getLogger(__name__)

# `created` was never started and `awaiting_approval` waits for a human: neither is a crash.
SWEEP_STATES = ("planning", "running", "gating", "applying")


async def sweep_once(
    factory: async_sessionmaker[AsyncSession], deps: AgentDeps, settings: Settings
) -> list[uuid.UUID]:
    """Recover up to `agent_sweep_max_runs` orphaned runs; returns the ids it took over."""
    now = datetime.now(UTC)
    async with factory() as s:
        ids = list(
            (
                await s.execute(
                    select(AiRun.id)
                    .where(
                        AiRun.state.in_(SWEEP_STATES),
                        AiRun.paused_at.is_(None),  # G3: a paused run waits for a human
                        or_(AiRun.lease_until.is_(None), AiRun.lease_until < now),
                    )
                    .order_by(AiRun.updated_at)
                    .limit(settings.agent_sweep_max_runs)
                )
            ).scalars()
        )
    await _expire_abandoned(factory, now)
    await retry_promotions(factory, deps, settings)
    taken: list[uuid.UUID] = []
    for rid in ids:
        async with factory() as s:
            run = await s.get(AiRun, rid)
            project = await s.get(Project, run.project_id) if run is not None else None
            if run is None or project is None:
                continue
            driver = RunDriver(
                s,
                deps.settings or settings,
                deps.toolbox,
                deps.approvals,
                ModelGateway(s, deps.settings or settings, deps.provider_factory),
                org_id=project.organization_id,
                gates=deps.gates,
            )
            try:
                # D-5: no request, so no actor role: S2-016 would deny applying an approved effect-hook
                # change. Only this drive runs as the system; the apply still re-validates every
                # approval (hash, spec, expiry), so nothing unapproved becomes applicable.
                with system_actor():
                    await driver.recover(rid, settings.agent_max_recoveries)
                taken.append(rid)
            except AppError:  # leased by a live driver, or finished meanwhile: not ours
                continue
            except Exception:  # noqa: BLE001 - one bad run never stops the sweep
                log.exception("agent run recovery crashed", extra={"run_id": str(rid)})
    return taken


async def retry_promotions(
    factory: async_sessionmaker[AsyncSession], deps: AgentDeps, settings: Settings, *, min_age_seconds: int = 60
) -> list[uuid.UUID]:
    """FX-3 / B-004: an `applied` run whose custom code is still `pending` (the process died, or git
    failed, between the spec apply and the commit to main) gets its stored files committed now.
    `promote_files` is idempotent, so a retry of a half-done promotion is safe. After
    MAX_PROMOTION_ATTEMPTS the promotion is marked failed (loudly) and left to a human."""
    from app.services.agent import promote as promote_lib
    from app.services.agent.run_service import mark_promotion

    done: list[uuid.UUID] = []
    async with factory() as s:
        ids = list(
            (
                await s.execute(
                    select(AiRun.id)
                    .where(AiRun.state == "applied", AiRun.promotion["state"].astext == "pending",
                           AiRun.finished_at < datetime.now(UTC) - timedelta(seconds=min_age_seconds))
                    .order_by(AiRun.updated_at)
                    .limit(settings.agent_sweep_max_runs)
                )
            ).scalars()
        )
    for rid in ids:
        async with factory() as s:
            run = await s.get(AiRun, rid)
            doc = run.promotion if run is not None else None
            files = promote_lib.decode(doc)
            if run is None or not isinstance(doc, dict):
                continue
            attempts = int(doc.get("attempts") or 0) + 1
            if files is None:
                await mark_promotion(s, rid, "failed", [], attempts=attempts)
                continue
            top = (await s.execute(select(func.max(AiStep.seq)).where(AiStep.run_id == rid))).scalar_one()
            try:
                out = await deps.approvals.promote(run, files)
                s.add(AiStep(run_id=rid, project_id=run.project_id, seq=int(top or 0) + 1, kind="system",
                             output={"promotion": out, "retried": attempts}))
                await s.commit()
                await mark_promotion(s, rid, "done", sorted(files), attempts=attempts)
                done.append(rid)
            except Exception as exc:  # noqa: BLE001 - one bad run never stops the sweep
                await s.rollback()
                log.error("promotion retry failed for run %s: %s", rid, type(exc).__name__)
                final = attempts >= promote_lib.MAX_PROMOTION_ATTEMPTS
                run = await s.get(AiRun, rid)
                if run is not None:
                    s.add(AiStep(run_id=rid, project_id=run.project_id, seq=int(top or 0) + 1, kind="system",
                                 ok=False, output={"promotion_failed": str(getattr(exc, "code", type(exc).__name__)),
                                                   "retried": attempts, "gave_up": final}))
                    run.promotion = {**doc, "attempts": attempts, **({"state": "failed"} if final else {})}
                    await s.commit()
    return done


async def _expire_abandoned(factory: async_sessionmaker[AsyncSession], now: datetime) -> list[uuid.UUID]:
    """N4: an `awaiting_approval` run whose approvals are all expired (and none pending/approved) can
    never go on: stop it (approval_expired) so it stops holding the project cap and the workspace's
    unique-index slot. A run with a still-pending, approved or denied-but-unread decision is left alone."""
    stopped: list[uuid.UUID] = []
    async with factory() as s:
        runs = list(
            (await s.execute(select(AiRun).where(AiRun.state == "awaiting_approval").limit(200))).scalars()
        )
        for run in runs:
            rows = list(
                (await s.execute(select(AiApproval).where(AiApproval.run_id == run.id))).scalars()
            )
            live = [a for a in rows if a.state != "expired" and not (a.state == "pending" and a.expires_at < now)]
            if not rows or live:
                continue
            res = await s.execute(
                update(AiRun)
                .where(AiRun.id == run.id, AiRun.state == "awaiting_approval")
                .values(
                    state="stopped", stop_code="approval_expired",
                    stop_detail="every approval this run was waiting for expired", lease_until=None,
                    lease_owner=None, finished_at=now,
                )
            )
            if res.rowcount:  # type: ignore[attr-defined]
                for a in rows:
                    if a.state == "pending":
                        a.state = "expired"
                stopped.append(run.id)
        await s.commit()
    return stopped


async def sweeper_loop(settings: Settings) -> None:
    """Sweep at startup and then forever. Started from the app lifespan."""
    from app.db import get_session_factory

    while True:
        try:
            await sweep_once(get_session_factory(), get_agent_deps(), settings)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("agent sweep crashed")
        await asyncio.sleep(settings.agent_sweep_interval_seconds)
