"""The durable runner (generated): start, claim under a lease, execute step by step, compensate, cancel.

Every state change is one short database transaction guarded by the lease token, so only the worker that
holds a run's lease can move it, and a worker that stalled past its lease and lost the run cannot overwrite
what the new holder did. A step's function runs OUTSIDE any transaction. The point of no return is the
transaction that records the step (`wf_steps`, primary key (run, step, phase)) and advances the cursor
together: after it commits, the step is never run again, by anyone. Before it commits, a crash means the step
is run again (at least once), with the same `idempotency_key`.

Times come from `now` (default: this host's clock). Keep hosts on NTP; a lease is the step's timeout plus
WORKFLOWS_LEASE_GRACE_SECONDS.
"""

import asyncio
import datetime as _dt
import json
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models._base import utcnow
from app.workflows import config, definitions, registry
from app.workflows.models import (
    ACTIVE,
    CANCELLED,
    COMPENSATE,
    COMPENSATED,
    COMPENSATING,
    COMPENSATION_FAILED,
    FAILED,
    FINISHED,
    FORWARD,
    PENDING,
    RUNNING,
    SUCCEEDED,
    Run,
    StepRecord,
)

logger = structlog.get_logger()

SessionFactory = async_sessionmaker[AsyncSession]


class UnknownWorkflow(ValueError):
    """The workflow name is not declared in the spec."""


class LeaseLost(Exception):
    """Another worker holds the run now: stop touching it."""


@dataclass
class Claimed:
    id: uuid.UUID
    workflow: str
    tenant_id: uuid.UUID | None
    status: str
    input: dict[str, Any]
    cursor: int
    attempt: int
    reason: str | None
    deadline_at: _dt.datetime
    lease_token: uuid.UUID


def backoff_delay(retry: Mapping[str, Any], attempt: int) -> float:
    base = float(retry["backoff_seconds"])
    if retry["backoff"] == "fixed":
        return min(base, config.BACKOFF_CAP_SECONDS)
    return min(base * 2 ** max(attempt - 1, 0), config.BACKOFF_CAP_SECONDS)


def idempotency_key(workflow: str, run_id: uuid.UUID, step: str, phase: str = FORWARD) -> str:
    """The same for every attempt of the same step (and phase) of the same run."""
    return f"{workflow}:{run_id}:{step}" + (":compensate" if phase == COMPENSATE else "")


def _describe(exc: BaseException) -> str:
    """What is stored about a failure: the class name only (a message may carry a payload or a secret)."""
    return type(exc).__name__[: config.MAX_ERROR_CHARS]


def tenant_clause(tenant_id: uuid.UUID | None) -> sa.ColumnElement[bool]:
    return Run.tenant_id.is_(None) if tenant_id is None else Run.tenant_id == tenant_id


def _json_size(value: object, what: str, limit: int) -> None:
    try:
        size = len(json.dumps(value, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be JSON (no NaN, no custom objects)") from None
    if size > limit:
        raise ValueError(f"{what} is at most {limit} bytes")


# --- start / cancel ---------------------------------------------------------------------------


async def start(
    workflow: str,
    input: dict[str, Any] | None = None,
    *,
    session: AsyncSession | None = None,
    tenant_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
    dedupe_key: str | None = None,
    now: _dt.datetime | None = None,
) -> uuid.UUID:
    """Add a run. With `session` it is part of the caller's transaction (commit/rollback is the caller's);
    without it a transaction of its own commits it. A `dedupe_key` is unique per tenant and workflow: a
    second start returns the first run's id."""
    declared = definitions.WORKFLOWS.get(workflow)
    if declared is None:
        raise UnknownWorkflow(f"unknown workflow {workflow!r}")
    body = {} if input is None else input
    if not isinstance(body, dict):
        raise TypeError("a workflow input is a dict")
    _json_size(body, "a workflow input", config.MAX_INPUT_BYTES)
    if dedupe_key is not None and not 0 < len(dedupe_key) <= 200:
        raise ValueError("dedupe_key is 1 to 200 characters")
    stamp = now or utcnow()
    run_id = uuid.uuid4()
    stmt = (
        pg_insert(Run)
        .values(
            id=run_id,
            workflow=workflow,
            tenant_id=tenant_id,
            status=PENDING,
            input=body,
            cursor=0,
            attempt=0,
            cancel_requested=False,
            next_run_at=stamp,
            deadline_at=stamp + _dt.timedelta(seconds=declared["timeout_seconds"]),
            dedupe_key=dedupe_key,
            created_by=created_by,
            created_at=stamp,
            updated_at=stamp,
        )
        .on_conflict_do_nothing()  # no target: either partial unique index may decide
        .returning(Run.id)
    )

    async def go(s: AsyncSession) -> uuid.UUID:
        new = (await s.execute(stmt)).scalar_one_or_none()
        if new is not None:
            return new
        return (
            await s.execute(
                sa.select(Run.id).where(Run.workflow == workflow, Run.dedupe_key == dedupe_key, tenant_clause(tenant_id))
            )
        ).scalar_one()

    if session is not None:
        return await go(session)
    from app.db import session_factory

    async with session_factory() as own:
        found = await go(own)
        await own.commit()
        return found


async def cancel(
    session: AsyncSession, run_id: uuid.UUID, tenant_id: uuid.UUID | None, *, now: _dt.datetime | None = None
) -> Run | None:
    """Ask a run to stop. None = no such run for this tenant. A run that has not started is cancelled at once;
    a running one is stopped by its worker at the next step boundary, undoing completed steps first when
    the workflow's on_failure is `compensate`. Finished runs and runs already undoing are left as they are.
    The caller commits."""
    stamp = now or utcnow()
    row = (
        await session.execute(
            sa.select(Run).where(Run.id == run_id, tenant_clause(tenant_id)).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.status in FINISHED or row.status == COMPENSATING:
        return row
    if row.status == PENDING and row.lease_token is None:
        row.status = CANCELLED
        row.finished_at = stamp
    row.cancel_requested = True
    row.updated_at = stamp
    return row


async def purge_finished(session: AsyncSession, *, now: _dt.datetime | None = None) -> int:
    cutoff = (now or utcnow()) - _dt.timedelta(days=config.retention_days())
    result = await session.execute(sa.delete(Run).where(Run.status.in_(FINISHED), Run.finished_at < cutoff))
    await session.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


# --- claiming ---------------------------------------------------------------------------------


async def claim(factory: SessionFactory, worker_id: str, *, now: _dt.datetime | None = None) -> Claimed | None:
    """Take the next due run, or one whose lease ran out, under a fresh lease. None if none is due."""
    stamp = now or utcnow()
    async with factory() as session:
        due = sa.and_(
            Run.status.in_(ACTIVE),
            Run.next_run_at <= stamp,
            sa.or_(Run.lease_token.is_(None), Run.lease_expires_at <= stamp),
        )
        row = (
            await session.scalars(
                sa.select(Run).where(due).order_by(Run.next_run_at, Run.created_at, Run.id).limit(1).with_for_update(skip_locked=True)
            )
        ).first()
        if row is None:
            await session.rollback()
            return None
        token = uuid.uuid4()
        if row.status == PENDING:
            row.status = RUNNING
        row.lease_token = token
        row.lease_expires_at = stamp + _dt.timedelta(seconds=config.lease_grace())
        row.locked_by = worker_id[:80]
        row.updated_at = stamp
        claimed = Claimed(
            id=row.id,
            workflow=row.workflow,
            tenant_id=row.tenant_id,
            status=row.status,
            input=dict(row.input),
            cursor=row.cursor,
            attempt=row.attempt,
            reason=row.reason,
            deadline_at=row.deadline_at,
            lease_token=token,
        )
        await session.commit()
        return claimed


# --- guarded state changes --------------------------------------------------------------------


async def _commit(
    factory: SessionFactory,
    c: Claimed,
    values: dict[str, Any],
    *,
    record: dict[str, Any] | None = None,
    inside: Callable[[AsyncSession], Awaitable[None]] | None = None,
    now: _dt.datetime | None = None,
) -> None:
    """One transaction: move the run (only while the lease is ours), enqueue a job if asked, record the step."""
    stamp = now or utcnow()
    async with factory() as session:
        moved = await session.execute(
            sa.update(Run)
            .where(Run.id == c.id, Run.lease_token == c.lease_token)
            .values(updated_at=stamp, **values)
            .returning(Run.id)
        )
        if moved.scalar_one_or_none() is None:
            await session.rollback()
            raise LeaseLost
        if inside is not None:
            await inside(session)
        if record is not None:
            await session.execute(
                pg_insert(StepRecord).values(run_id=c.id, finished_at=stamp, **record).on_conflict_do_nothing()
            )
        await session.commit()


def _finish_values(status: str, stamp: _dt.datetime, error: str | None, failed_step: str | None) -> dict[str, Any]:
    values: dict[str, Any] = {"status": status, "finished_at": stamp, "lease_token": None, "lease_expires_at": None}
    if error is not None:  # a run that ends after undoing keeps the error and step that started the undo
        values["error"] = error
        values["failed_step"] = failed_step
    return values


async def _cancel_requested(factory: SessionFactory, run_id: uuid.UUID) -> bool:
    async with factory() as session:
        return bool((await session.execute(sa.select(Run.cancel_requested).where(Run.id == run_id))).scalar_one_or_none())


async def _results(factory: SessionFactory, run_id: uuid.UUID) -> dict[str, Any]:
    async with factory() as session:
        rows = await session.execute(
            sa.select(StepRecord.step, StepRecord.result).where(
                StepRecord.run_id == run_id, StepRecord.phase == FORWARD, StepRecord.status == "succeeded"
            )
        )
        return {step: result for step, result in rows}


# --- executing a run --------------------------------------------------------------------------


async def drive(factory: SessionFactory, c: Claimed, *, now: _dt.datetime | None = None) -> str:
    """Run a claimed run until it finishes, waits for a retry, or the lease is lost.
    Returns `finished`, `released` (a retry is scheduled) or `lost`."""
    wf = definitions.WORKFLOWS.get(c.workflow)
    try:
        if wf is None:
            await _commit(factory, c, _finish_values(FAILED, now or utcnow(), "UnknownWorkflow", None), now=now)
            return "finished"
        return await _drive(factory, c, wf, now)
    except LeaseLost:
        logger.warning("workflow_lease_lost", run_id=str(c.id), workflow=c.workflow)
        return "lost"


async def _drive(factory: SessionFactory, c: Claimed, wf: Mapping[str, Any], now: _dt.datetime | None) -> str:
    steps: list[Mapping[str, Any]] = list(wf["steps"])
    status, cursor, reason = c.status, c.cursor, c.reason
    while True:
        stamp = now or utcnow()
        if status == RUNNING:
            if await _cancel_requested(factory, c.id):
                if wf["on_failure"] == "compensate" and cursor > 0:
                    values = {"status": COMPENSATING, "reason": "cancel", "cursor": cursor - 1, "attempt": 0}
                    await _commit(factory, c, values, now=now)
                    status, cursor, reason = COMPENSATING, cursor - 1, "cancel"
                else:
                    await _commit(factory, c, _finish_values(CANCELLED, stamp, None, None), now=now)
                    return "finished"
                continue
            if stamp > c.deadline_at:
                status, cursor, reason = await _fail_forward(factory, c, wf, cursor, None, "WorkflowTimeout", now)
                if status == FAILED:
                    return "finished"
                continue
            if cursor >= len(steps):
                await _commit(factory, c, _finish_values(SUCCEEDED, stamp, None, None), now=now)
                return "finished"
            phase = FORWARD
        else:
            while cursor >= 0 and not steps[cursor]["compensate"]:
                cursor -= 1
            if cursor < 0:
                end = CANCELLED if reason == "cancel" else COMPENSATED
                await _commit(factory, c, {**_finish_values(end, stamp, None, None), "cursor": -1}, now=now)
                return "finished"
            phase = COMPENSATE
        step_def = steps[cursor]
        outcome = await _execute(factory, c, wf, step_def, cursor, phase, reason, now)
        if outcome[0] == "released":
            return "released"
        status, cursor, reason = outcome[1], outcome[2], outcome[3]
        if status in FINISHED:
            return "finished"


async def _fail_forward(
    factory: SessionFactory,
    c: Claimed,
    wf: Mapping[str, Any],
    cursor: int,
    step_name: str | None,
    error: str,
    now: _dt.datetime | None,
    record: dict[str, Any] | None = None,
) -> tuple[str, int, str | None]:
    """A forward step failed for good (or the run timed out): undo completed steps, or stop."""
    stamp = now or utcnow()
    if wf["on_failure"] == "compensate" and cursor > 0:
        values = {
            "status": COMPENSATING,
            "reason": "failure",
            "cursor": cursor - 1,
            "attempt": 0,
            "error": error,
            "failed_step": step_name,
            "next_run_at": stamp,
        }
        await _commit(factory, c, values, record=record, now=now)
        return COMPENSATING, cursor - 1, "failure"
    await _commit(factory, c, _finish_values(FAILED, stamp, error, step_name), record=record, now=now)
    return FAILED, cursor, None


async def _execute(
    factory: SessionFactory,
    c: Claimed,
    wf: Mapping[str, Any],
    step_def: Mapping[str, Any],
    cursor: int,
    phase: str,
    reason: str | None,
    now: _dt.datetime | None,
) -> tuple[Any, ...]:
    """One attempt of one step. Returns ("released",) or ("next", status, cursor, reason)."""
    stamp = now or utcnow()
    name = step_def["name"]
    retry = step_def["retry"]
    key = idempotency_key(c.workflow, c.id, name, phase)
    # 1. count the attempt and extend the lease to cover it, before anything runs (a crash still counts)
    async with factory() as session:
        counted = await session.execute(
            sa.update(Run)
            .where(Run.id == c.id, Run.lease_token == c.lease_token)
            .values(
                attempt=Run.attempt + 1,
                cursor=cursor,
                updated_at=stamp,
                lease_expires_at=stamp + _dt.timedelta(seconds=step_def["timeout_seconds"] + config.lease_grace()),
            )
            .returning(Run.attempt)
        )
        attempt = counted.scalar_one_or_none()
        if attempt is None:
            await session.rollback()
            raise LeaseLost
        await session.commit()
    status = COMPENSATING if phase == COMPENSATE else RUNNING
    error: str | None = None
    result: Any = None
    if attempt > retry["max_attempts"]:
        error = "Abandoned"  # the worker died on every attempt: do not run it again
    else:
        results = await _results(factory, c.id)
        ctx = registry.StepContext(
            run_id=c.id,
            workflow=c.workflow,
            step=name,
            attempt=attempt,
            max_attempts=retry["max_attempts"],
            input=c.input,
            results=results,
            idempotency_key=key,
            tenant_id=c.tenant_id,
            compensating=phase == COMPENSATE,
            reason=reason if phase == COMPENSATE else None,
            result=results.get(name) if phase == COMPENSATE else None,
        )
        logger.info("workflow_step_started", run_id=str(c.id), workflow=c.workflow, step=name, phase=phase, attempt=attempt)
        fn = registry.get_compensation(c.workflow, name) if phase == COMPENSATE else registry.get_step(c.workflow, name)
        inside: Callable[[AsyncSession], Awaitable[None]] | None = None
        if step_def["kind"] == "job" and phase == FORWARD:
            inside = _enqueue_job(step_def["job"], c, name, key)
        elif fn is None:
            error = "NoHandler"
        if error is None and fn is not None:
            try:
                result = await asyncio.wait_for(fn(ctx), step_def["timeout_seconds"])
                if result is not None:
                    _json_size(result, "a step result", config.MAX_RESULT_BYTES)
            except TimeoutError:
                error = "Timeout"
            except asyncio.CancelledError:
                raise  # shutdown: the lease runs out and another worker resumes the run
            except Exception as exc:
                error = _describe(exc)
        if error is None:
            record = {"step": name, "phase": phase, "status": "succeeded", "attempts": attempt, "result": result, "idempotency_key": key}
            next_cursor = cursor + 1 if phase == FORWARD else cursor - 1
            await _commit(
                factory, c, {"cursor": next_cursor, "attempt": 0, "next_run_at": stamp}, record=record, inside=inside, now=now
            )
            logger.info("workflow_step_done", run_id=str(c.id), workflow=c.workflow, step=name, phase=phase)
            return ("next", status, next_cursor, reason)
    logger.error("workflow_step_failed", run_id=str(c.id), workflow=c.workflow, step=name, phase=phase, attempt=attempt, error=error)
    if error != "Abandoned" and attempt < retry["max_attempts"]:
        # a durable retry: release the run, due again after the backoff
        values = {
            "next_run_at": stamp + _dt.timedelta(seconds=backoff_delay(retry, attempt)),
            "lease_token": None,
            "lease_expires_at": None,
            "error": error,
        }
        await _commit(factory, c, values, now=now)
        return ("released",)
    record = {
        "step": name, "phase": phase, "status": "failed", "attempts": attempt, "result": None,
        "idempotency_key": key, "error": error,
    }
    if phase == COMPENSATE:
        await _commit(factory, c, _finish_values(COMPENSATION_FAILED, stamp, error, name), record=record, now=now)
        return ("next", COMPENSATION_FAILED, cursor, reason)
    new_status, new_cursor, new_reason = await _fail_forward(factory, c, wf, cursor, name, error or "Error", now, record)
    return ("next", new_status, new_cursor, new_reason)


def _enqueue_job(job: str, c: Claimed, step: str, key: str) -> Callable[[AsyncSession], Awaitable[None]]:
    async def inside(session: AsyncSession) -> None:
        from app.jobs import queue  # only a project with the jobs block has job steps

        await queue.enqueue(
            job,
            {"workflow_run_id": str(c.id), "workflow": c.workflow, "step": step, "idempotency_key": key, "input": c.input},
            session=session,
            dedupe_key=key,  # a crash after the enqueue but before the record must not enqueue twice
            tenant_id=c.tenant_id,
        )

    return inside
