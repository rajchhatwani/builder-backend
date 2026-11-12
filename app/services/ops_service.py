"""Operator view (CP-5V): job heartbeats, an in-process go-live check, and the admin overview.

`golive_checks` ports scripts/golive_check.sh into checks that are safe to run inside the API
process: they never need root, never open a network connection and never run a subprocess, and they
return no secret values. A check that would need any of that returns `skipped` with the reason (and
the script to run instead). Statuses: pass | fail | warn | skipped.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import crypto, jobs_cron, metering, rls
from app.core.production_checks import production_problems
from app.db import get_session_factory
from app.models.metrics import Report, ReportRun
from app.models.ops import JobHeartbeat
from app.models.workspace import Workspace
from app.services.workspace_service import ACTIVE_STATES

STALE_FACTOR = 3  # a job that has not run for this many intervals is reported stale


# -- heartbeats ----------------------------------------------------------------------------------


async def record_heartbeat(job: str, ok: bool, error: str | None = None, interval: int | None = None) -> None:
    """Upsert the job's heartbeat on its own session. Never raises: a monitoring row must not stop a job."""
    try:
        now = datetime.now(UTC)
        values = {
            "job": job,
            "last_run_at": now,
            "last_status": "ok" if ok else "failed",
            "last_error": error[:120] if error else None,
            "interval_seconds": interval,
            "runs": 1,
        }
        async with get_session_factory()() as db:
            stmt = pg_insert(JobHeartbeat).values(**values)
            await db.execute(
                stmt.on_conflict_do_update(
                    index_elements=["job"],
                    set_={
                        "last_run_at": now,
                        "last_status": values["last_status"],
                        "last_error": values["last_error"],
                        "interval_seconds": interval
                        if interval is not None
                        else JobHeartbeat.interval_seconds,
                        "runs": JobHeartbeat.runs + 1,
                    },
                )
            )
            await db.commit()
    except Exception:  # noqa: BLE001 - best effort by design
        return


def configured_intervals() -> dict[str, int]:
    from app.jobs import scheduler  # noqa: PLC0415 - the scheduler imports this module

    return {name: every for name, _job, every in scheduler.jobs()}


async def scheduler_status(db: AsyncSession, now: datetime) -> dict[str, Any]:
    intervals = configured_intervals()
    rows = {r.job: r for r in (await db.execute(select(JobHeartbeat))).scalars()}
    jobs: list[dict[str, Any]] = []
    for name in sorted(set(intervals) | set(rows)):
        row = rows.get(name)
        every = intervals.get(name) or (row.interval_seconds if row else None)
        last = row.last_run_at if row else None
        jobs.append(
            {
                "job": name,
                "interval_seconds": every,
                "last_run_at": last,
                "last_status": row.last_status if row else None,
                "last_error": row.last_error if row else None,
                "runs": int(row.runs) if row else 0,
                "next_expected_at": (last + timedelta(seconds=every)) if last and every else None,
                "stale": bool(last is None or (every and now - last > timedelta(seconds=every * STALE_FACTOR))),
            }
        )
    return {"jobs": jobs}


# -- report schedules ----------------------------------------------------------------------------


async def report_status(db: AsyncSession, now: datetime) -> dict[str, Any]:
    enabled = (await db.execute(select(func.count()).select_from(Report).where(Report.enabled.is_(True)))).scalar_one()
    total = (await db.execute(select(func.count()).select_from(Report))).scalar_one()
    last_run = (await db.execute(select(func.max(ReportRun.created_at)))).scalar_one()
    next_due: datetime | None = None
    rows = (await db.execute(select(Report.schedule, Report.timezone).where(Report.enabled.is_(True)))).all()
    for schedule, tz in rows:
        try:
            nxt = jobs_cron.next_fire(jobs_cron.parse(schedule), jobs_cron.zone(tz), now)
        except jobs_cron.CronError:
            continue
        if nxt is not None and (next_due is None or nxt < next_due):
            next_due = nxt
    return {
        "enabled_schedules": int(enabled),
        "disabled_schedules": int(total) - int(enabled),
        "last_run_at": last_run,
        "next_run_at": next_due,
    }


# -- idle workspaces, usage defaults, key provider -----------------------------------------------


async def idle_workspace_status(db: AsyncSession, settings: Settings, now: datetime) -> dict[str, Any]:
    ttl = settings.workspace_idle_ttl_days
    live_q = select(func.count()).select_from(Workspace).where(Workspace.state.in_(ACTIVE_STATES))
    live = (await db.execute(live_q)).scalar_one()
    idle = (
        await db.execute(live_q.where(Workspace.updated_at < now - timedelta(days=ttl)))
    ).scalar_one()
    return {"ttl_days": ttl, "live_workspaces": int(live), "idle_past_ttl": int(idle)}


def usage_defaults() -> list[dict[str, Any]]:
    return [
        {"metric": name, "unit": m.unit, "period": m.period, "default_limit": m.default_limit}
        for name, m in metering.METRICS.items()
    ]


def key_provider_status(settings: Settings) -> dict[str, Any]:
    """Kind and health of the key provider. Key ids are not secret; key material and the file path /
    command are never returned."""
    out: dict[str, Any] = {"kind": settings.key_provider, "healthy": False, "active_key_id": None, "key_count": 0, "error": None}
    try:
        ring = crypto._ring  # noqa: SLF001
        prov = crypto._provider  # noqa: SLF001
        if ring is None and (settings.key_provider == "command" or type(prov).__name__ == "CommandKeyProvider"):
            # A cold command provider would spawn a process inside the async handler: report, never load.
            out["error"] = "not_loaded"
            return out
        ring = crypto._get_ring()  # noqa: SLF001 - env/file/kms load is cheap and has no subprocess
        out.update(healthy=True, active_key_id=ring.active_id, key_count=len(ring.keys))
    except Exception as exc:  # noqa: BLE001 - report the type only
        out["error"] = type(exc).__name__
    return out


# -- go-live checks ------------------------------------------------------------------------------


def _c(check: str, status: str, detail: str) -> dict[str, str]:
    return {"check": check, "status": status, "detail": detail}


async def golive_checks(db: AsyncSession, settings: Settings) -> dict[str, Any]:
    results: list[dict[str, str]] = []

    if settings.sandbox_runner_url and settings.sandbox_runner_token is not None:
        results.append(_c("P1 runner configured", "pass", "runner url and token are set"))
    else:
        results.append(_c("P1 runner configured", "fail", "BUILDER_SANDBOX_RUNNER_URL / _TOKEN unset"))
    results.append(
        _c("P1 runner reachable", "skipped", "needs a network call; run scripts/golive_check.sh on the host")
    )
    if settings.sandbox_runtime == "runc":
        results.append(_c("P1 runtime", "fail", "sandbox_runtime is runc (not an isolation boundary)"))
    else:
        results.append(_c("P1 runtime", "pass", f"configured runtime {settings.sandbox_runtime}"))
    results.append(
        _c("P1 runtime registered", "skipped", "needs docker on the host; run scripts/golive_check.sh")
    )
    results.append(_c("P2 firewall", "skipped", "needs root / iptables; run scripts/sandbox_firewall.sh status"))

    try:
        conn = await db.connection()
        problems = await rls.role_problems(conn)
        results.append(
            _c("P3/P5 RLS API role", "fail", "; ".join(problems))
            if problems
            else _c("P3/P5 RLS API role", "pass", "API role cannot bypass RLS")
        )
    except Exception as exc:  # noqa: BLE001
        results.append(_c("P3/P5 RLS API role", "fail", f"could not inspect the role ({type(exc).__name__})"))

    prod = production_problems(settings)
    if prod:
        results.append(_c("P4/P5 production settings", "fail", "; ".join(prod)))
    elif not settings.environment_explicit or settings.environment in ("local", "test"):
        results.append(_c("P4/P5 production settings", "skipped", "environment is local/test or not set explicitly"))
    else:
        results.append(_c("P4/P5 production settings", "pass", "ok"))

    missing = [
        n
        for n, ok in (
            ("preview_scheduler_enabled", settings.preview_scheduler_enabled),
            ("preview_root", bool(settings.preview_root)),
            ("rls_enabled", settings.rls_enabled),
        )
        if not ok
    ]
    results.append(
        _c("P4 scheduler/preview_root/rls", "fail", "not set: " + ", ".join(missing))
        if missing
        else _c("P4 scheduler/preview_root/rls", "pass", "scheduler on, preview_root set, rls on")
    )

    kp = key_provider_status(settings)
    results.append(
        _c("P6 key provider", "pass", f"{kp['kind']} provider, active key id {kp['active_key_id']}")
        if kp["healthy"]
        else _c("P6 key provider", "fail", f"{kp['kind']} provider failed to load ({kp['error']})")
    )

    url = settings.public_api_url or ""
    if url and not url.startswith(("http://localhost", "http://127.")) and not settings.trust_proxy_headers:
        results.append(
            _c(
                "P4 proxy headers",
                "warn",
                "public_api_url is set but trust_proxy_headers=false: behind a reverse proxy all preview "
                "visitors share one rate bucket",
            )
        )
    else:
        results.append(_c("P4 proxy headers", "pass", "ok"))

    return {
        "ran_at": datetime.now(UTC),
        "passed": sum(r["status"] == "pass" for r in results),
        "failed": sum(r["status"] == "fail" for r in results),
        "warnings": sum(r["status"] == "warn" for r in results),
        "skipped": sum(r["status"] == "skipped" for r in results),
        "ok": not any(r["status"] == "fail" for r in results),
        "checks": results,
    }


async def operations_overview(db: AsyncSession, settings: Settings) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "generated_at": now,
        "scheduler": await scheduler_status(db, now),
        "idle_workspaces": await idle_workspace_status(db, settings, now),
        "reports": await report_status(db, now),
        "usage_defaults": usage_defaults(),
        "key_provider": key_provider_status(settings),
        "golive": await golive_checks(db, settings),
    }
