"""Crash-resume sweeper (B-003): re-drive agent runs whose driver died.

A run that is mid-flight (planning/running/gating/applying) but whose lease has expired has no
driver. The sweeper takes the lease with the same compare-and-set a manual resume uses, so a live
driver is never disturbed, and drives the run on from its persisted steps. It runs once at start
and then every `agent_sweep_interval_seconds` (started from the app lifespan).
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.exceptions import AppError
from app.models.agent import AiApproval, AiRun
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
                        or_(AiRun.lease_until.is_(None), AiRun.lease_until < now),
                    )
                    .order_by(AiRun.updated_at)
                    .limit(settings.agent_sweep_max_runs)
                )
            ).scalars()
        )
    await _expire_abandoned(factory, now)
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
