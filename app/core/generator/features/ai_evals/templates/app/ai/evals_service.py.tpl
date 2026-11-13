"""Eval harness service (generated). The rules, in one place.

* A suite belongs to one agent and holds cases (goal, expect_actions, forbid_actions). Running it runs EVERY case through the
  agent runtime (`agents_service.start_run(dry=True)`): mode `suggest`, nothing executes, the rows are flagged `eval` and
  hidden from the inbox, and the model is reached only through the gateway (budget applies).
* A case passes when every expected action is proposed and not rejected by policy, and no forbidden action is proposed. A
  gateway failure (or an unreadable answer) on a case is an `error` and counts as failed.
* score_bp = passed * 10000 // total; the run passes when score_bp >= the suite's pass_bp. The run row is written when the
  suite is finished, so "the latest finished run" is the newest row. A failing run re-locks `auto` for agents whose
  require_eval names the suite.
"""

import types as _types
import typing as _t
import uuid as _uuid

import sqlalchemy as _sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import agents_schemas as _a
from app.ai import agents_service as _agents
from app.ai import evals_config as _config
from app.ai import evals_schemas as _s
from app.ai import service as _gateway
from app.ai.evals_models import AiEvalRun
from app.core.errors import AppError


def _scoped(stmt: _t.Any, tenant: _uuid.UUID | None) -> _t.Any:
    return stmt.where(AiEvalRun.tenant_id == tenant) if tenant is not None else stmt


def _out(r: AiEvalRun) -> _s.EvalRunOut:
    return _s.EvalRunOut(
        id=r.id,
        suite=r.suite,
        agent=r.agent,
        score_bp=r.score_bp,
        passed=r.passed,
        total=r.total,
        passed_count=r.passed_count,
        results=[_s.CaseResultOut(**c) for c in r.results],
        created_by=r.created_by,
        created_at=r.created_at,
    )


async def list_suites(session: AsyncSession, user: _t.Any) -> list[_s.SuiteOut]:
    tenant = _gateway.tenant_of(user)
    out: list[_s.SuiteOut] = []
    for name, suite in sorted(_config.SUITES.items()):
        latest = (
            await session.execute(
                _scoped(_sa.select(AiEvalRun).where(AiEvalRun.suite == name), tenant).order_by(AiEvalRun.created_at.desc(), AiEvalRun.id.desc()).limit(1)
            )
        ).scalar_one_or_none()
        out.append(
            _s.SuiteOut(
                name=name,
                agent=str(suite["agent"]),
                pass_bp=_t.cast(int, suite["pass_bp"]),
                case_count=len(_t.cast(list[object], suite["cases"])),
                latest=_s.LatestOut(id=latest.id, passed=latest.passed, score_bp=latest.score_bp, created_at=latest.created_at)
                if latest is not None
                else None,
            )
        )
    await session.commit()
    return out


async def run_suite(session: AsyncSession, user: _t.Any, suite_name: str) -> _s.EvalRunOut:
    tenant = _gateway.tenant_of(user)
    caller: _uuid.UUID | None = getattr(user, "id", None)  # plain value: a rollback expires the user object
    # a plain stand-in for the signed-in user: nothing below reads the session-bound ORM object after a rollback
    plain = _types.SimpleNamespace(id=caller, tenant_id=getattr(user, "tenant_id", None), roles=list(user.roles))
    suite = _config.SUITES.get(suite_name)
    if suite is None:
        raise AppError("unknown_suite", f"there is no eval suite {suite_name[:40]!r}", 404)
    agent = str(suite["agent"])
    results: list[dict[str, _t.Any]] = []
    for case in _t.cast(list[dict[str, _t.Any]], suite["cases"]):
        proposed: list[str] = []
        error_code: str | None = None
        passed = False
        try:
            run, _ = await _agents.start_run(session, plain, agent, _a.RunIn(goal=case["goal"]), dry=True)
        except AppError as exc:  # budget, provider, per-call cap ...: the case failed, the suite goes on
            await session.rollback()
            error_code = exc.code
        else:
            proposed = [p.action for p in run.proposals]
            error_code = run.error_code
            accepted = {p.action for p in run.proposals if p.status != "rejected_by_policy"}
            passed = (
                run.status == "completed"
                and all(name in accepted for name in case["expect_actions"])
                and not any(name in proposed for name in case["forbid_actions"])
            )
        results.append({"case": case["name"], "passed": passed, "proposed": proposed, "error_code": error_code})
    total = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    score = passed_count * 10_000 // total if total else 0
    row = AiEvalRun(
        id=_uuid.uuid4(),
        suite=suite_name,
        agent=agent,
        score_bp=score,
        passed=score >= _t.cast(int, suite["pass_bp"]),
        total=total,
        passed_count=passed_count,
        results=results,
        created_by=caller,
    )
    if tenant is not None:
        row.tenant_id = tenant
    session.add(row)
    await session.commit()
    return await get_run(session, plain, row.id)


async def get_run(session: AsyncSession, user: _t.Any, run_id: _uuid.UUID) -> _s.EvalRunOut:
    tenant = _gateway.tenant_of(user)
    stmt = _scoped(_sa.select(AiEvalRun).where(AiEvalRun.id == run_id), tenant).execution_options(populate_existing=True)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise AppError("not_found", "eval run not found", 404)
    return _out(row)


async def list_runs(
    session: AsyncSession, user: _t.Any, limit: int, offset: int, suite: str | None
) -> tuple[list[_s.EvalRunOut], int]:
    tenant = _gateway.tenant_of(user)
    conditions: list[_t.Any] = [AiEvalRun.suite == suite] if suite is not None else []
    total = await session.scalar(_scoped(_sa.select(_sa.func.count()).select_from(AiEvalRun).where(*conditions), tenant))
    rows = (
        await session.execute(
            _scoped(_sa.select(AiEvalRun).where(*conditions), tenant)
            .order_by(AiEvalRun.created_at.desc(), AiEvalRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars()
    return [_out(r) for r in rows], total or 0
