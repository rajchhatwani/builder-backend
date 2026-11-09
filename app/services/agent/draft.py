"""The per-run spec draft (H2).

The agent never writes the live spec. Its spec operations are recorded as `ai_draft_ops` rows and
folded (pure `registry.plan`) over the spec the plan was approved on (`run.plan["base_spec"]`).
Every read the run makes (tools, gates, the approval hash and diff) sees that draft. Only an
approved final review replays the rows onto the live project, in order, through OpsService; any
other end of the run deletes them. Before the plan is approved there is no draft: reads are live.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.spec_models import Spec
from app.core.validation import ValidationIssue, validate
from app.exceptions import AppError
from app.models.agent import AiDraftOp, AiRun, AiStep
from app.models.spec_op import SpecOp
from app.services.ops.canon import canonical_hash
from app.services.ops.registry import dump, plan
from app.services.ops.scope import Actor
from app.services.spec_service import SpecService

LIVE_STATES = frozenset({"created", "planning", "awaiting_approval", "running", "gating", "applying"})


async def spec_seq(session: AsyncSession, project_id: uuid.UUID) -> int:
    q = select(func.coalesce(func.max(SpecOp.seq), 0)).where(SpecOp.project_id == project_id)
    return int((await session.execute(q)).scalar_one())


async def _run_row(session: AsyncSession, run_id: uuid.UUID, project_id: uuid.UUID) -> tuple[str, Any] | None:
    row = (
        await session.execute(
            select(AiRun.state, AiRun.plan).where(AiRun.id == run_id, AiRun.project_id == project_id)
        )
    ).first()
    return None if row is None else (row[0], row[1])


def _base(plan_doc: Any) -> Spec | None:
    raw = plan_doc.get("base_spec") if isinstance(plan_doc, dict) else None
    return Spec.model_validate(raw) if isinstance(raw, dict) else None


async def _ops(session: AsyncSession, run_id: uuid.UUID) -> list[AiDraftOp]:
    q = select(AiDraftOp).where(AiDraftOp.run_id == run_id).order_by(AiDraftOp.seq)
    return list((await session.execute(q)).scalars())


def _fold(base: Spec, ops: list[AiDraftOp]) -> Spec:
    spec = base
    for op in ops:
        spec = plan(spec, op.op_type, op.payload).after
    return spec


async def run_spec(session: AsyncSession, run_id: uuid.UUID, project_id: uuid.UUID) -> Spec:
    """The spec this run sees: its draft once the plan is approved, else the live spec. A run id
    that belongs to another project never yields a draft."""
    found = await _run_row(session, run_id, project_id)
    base = _base(found[1]) if found else None
    if base is None:
        return await SpecService(session).assemble(project_id)
    return _fold(base, await _ops(session, run_id))


def _key(i: ValidationIssue) -> tuple[str, str, str]:
    return (i.path, i.code, i.message)


async def add_draft_op(
    session: AsyncSession,
    run_id: uuid.UUID,
    project_id: uuid.UUID,
    op_type: str,
    payload: dict[str, Any],
    *,
    commit: bool = True,
) -> int:
    """Validate one operation against the draft (same rules as OpsService: 422 and nothing
    recorded when it adds a validation issue) and append it. Returns the draft sequence."""
    found = await _run_row(session, run_id, project_id)
    base = _base(found[1]) if found else None
    if found is None or base is None:
        raise AppError("draft_unavailable", "the run has no spec draft (the plan is not approved)", 409)
    # Serialise with cancel/stop: once the run is over nothing may be added to its draft.
    state = (
        await session.execute(select(AiRun.state).where(AiRun.id == run_id).with_for_update())
    ).scalar_one()
    if state not in LIVE_STATES:
        raise AppError("run_finished", f"run is already {state}", 409)
    ops = await _ops(session, run_id)
    before = _fold(base, ops)
    planned = plan(before, op_type, payload)
    known = {_key(i) for i in validate(before)}
    fresh = [i for i in validate(planned.after) if _key(i) not in known]
    if fresh:
        raise AppError(
            code="spec_invalid",
            message=f"the operation leaves {len(fresh)} new validation issue(s)",
            status_code=422,
            details=[i.model_dump() for i in fresh],
        )
    seq = (ops[-1].seq if ops else 0) + 1
    session.add(
        AiDraftOp(run_id=run_id, project_id=project_id, seq=seq, op_type=op_type, payload=dump(planned.payload))
    )
    if commit:
        await session.commit()
    else:  # the caller commits this together with its own writes (approved-action execution)
        await session.flush()
    return seq


class LeaseLost(Exception):
    """The caller no longer holds the run's lease: it must not touch the run's draft."""


async def drop_draft(session: AsyncSession, run_id: uuid.UUID, *, owner: str | None = None) -> int:
    """Delete the run's draft ops. With `owner`, only while that driver still holds the lease: the
    check and the delete are one transaction under the run row lock (S1-001), else LeaseLost."""
    if owner is not None:
        held = (
            await session.execute(
                select(AiRun.id)
                .where(AiRun.id == run_id, AiRun.lease_owner == owner, AiRun.state.in_(LIVE_STATES))
                .with_for_update()
            )
        ).scalar_one_or_none()
        if held is None:
            await session.rollback()
            raise LeaseLost()
    res = await session.execute(delete(AiDraftOp).where(AiDraftOp.run_id == run_id))
    await session.commit()
    return int(res.rowcount or 0)  # type: ignore[attr-defined]


@dataclass
class ApplyOutcome:
    status: str  # applied | conflict | failed
    detail: str = ""
    ops: int = 0


async def apply_draft(
    session: AsyncSession, run_id: uuid.UUID, *, owner: str | None = None, promotion: dict[str, Any] | None = None
) -> ApplyOutcome:
    """Replay the draft onto the live project, only if the live spec is exactly the plan's base.
    A person's (or another run's) change in between is a conflict: nothing is written.

    The live spec, the draft deletion and the run's `applied` state commit in ONE transaction
    (S1-005): a crash or a cancel can no longer leave a changed spec behind a run that is not
    `applied`, and a repeated call on an applied run is a no-op. `promotion` (FX-3) is stored on the run
    in that same transaction, so the custom code that goes with the spec is never lost to a crash."""
    from app.services.ops.service import OpsService

    run = await session.get(AiRun, run_id, populate_existing=True)
    if run is None:
        return ApplyOutcome("failed", "run not found")
    if run.state == "applied":
        return ApplyOutcome("applied", "already applied")
    project_id = run.project_id
    doc = run.plan if isinstance(run.plan, dict) else {}
    base, base_seq = _base(doc), doc.get("base_spec_seq")
    actor = Actor("agent", user_id=run.created_by)
    if base is None or not isinstance(base_seq, int):
        return ApplyOutcome("failed", "the run has no recorded base spec")
    rows = await _ops(session, run_id)
    expected = canonical_hash(_fold(base, rows))

    async def still_applying() -> None:
        # Under the project lock. Claim the run row (state applying -> applied, lease cleared) in
        # the batch's own transaction: a cancel/stop/takeover that won the race wins, and if the
        # batch fails afterwards the claim is rolled back with it.
        cond = [AiRun.id == run_id, AiRun.state == "applying"]
        if owner is not None:
            cond.append(AiRun.lease_owner == owner)
        claimed = await session.execute(
            update(AiRun)
            .where(*cond)
            .values(state="applied", finished_at=datetime.now(UTC), lease_owner=None, lease_until=None,
                    **({"promotion": promotion} if promotion is not None else {}))
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount == 0:  # type: ignore[attr-defined]
            st = (await session.execute(select(AiRun.state).where(AiRun.id == run_id))).scalar_one()
            raise AppError("apply_cancelled", f"the run is {st}; nothing was applied", 409)
        top = (await session.execute(select(func.max(AiStep.seq)).where(AiStep.run_id == run_id))).scalar_one()
        session.add(
            AiStep(run_id=run_id, project_id=project_id, seq=int(top or 0) + 1, kind="system",
                   output={"draft": "applied", "ops": len(rows)})
        )
        await session.execute(delete(AiDraftOp).where(AiDraftOp.run_id == run_id))

    try:
        await OpsService(session).apply_batch(
            project_id,
            [(r.op_type, r.payload) for r in rows],
            actor,
            base_seq=base_seq,
            expect_before=canonical_hash(base),
            expect_after=expected,
            guard=still_applying,
        )
    except AppError as exc:  # the whole batch was rolled back: live is exactly as it was
        await session.rollback()
        await session.get(AiRun, run_id, populate_existing=True)  # the rollback expired the caller's run row
        if exc.code in ("apply_conflict", "apply_cancelled"):
            return ApplyOutcome("conflict", exc.message, len(rows))
        return ApplyOutcome("failed", exc.code or "apply_failed", len(rows))
    except Exception as exc:
        await session.rollback()
        await session.get(AiRun, run_id, populate_existing=True)
        return ApplyOutcome("failed", type(exc).__name__, len(rows))
    return ApplyOutcome("applied", "", len(rows))
