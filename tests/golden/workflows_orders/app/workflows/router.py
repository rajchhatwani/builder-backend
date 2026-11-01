"""Start, inspect and cancel workflow runs (generated). Default deny: a caller needs one of the workflow's
`roles`; a run of another tenant is a 404, never a 403. Inputs and step results are never returned (they may
hold personal data): an inspection shows the status, the steps and the failing step."""

import datetime as _dt
import uuid
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from app.auth.deps import CurrentPrincipal, get_principal
from app.core.errors import AppError, NotFoundError
from app.db import SessionDep
from app.workflows import definitions, engine
from app.workflows.models import Run, StepRecord

router = APIRouter(prefix="/workflows", tags=["workflows"], dependencies=[Depends(get_principal)])


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)


class StepOut(BaseModel):
    step: str
    phase: str
    status: str
    attempts: int
    error: str | None
    finished_at: _dt.datetime


class RunOut(BaseModel):
    id: uuid.UUID
    workflow: str
    status: str
    cursor: int
    cancel_requested: bool
    error: str | None
    failed_step: str | None
    created_at: _dt.datetime
    updated_at: _dt.datetime
    finished_at: _dt.datetime | None


class RunDetail(RunOut):
    steps: list[StepOut]


def _allowed(principal: CurrentPrincipal, workflow: str) -> bool:
    return bool(set(principal.roles) & set(definitions.WORKFLOWS[workflow]["roles"]))


def _readable(principal: CurrentPrincipal) -> list[str]:
    return [name for name in definitions.WORKFLOWS if _allowed(principal, name)]


async def _own_run(session: SessionDep, principal: CurrentPrincipal, run_id: uuid.UUID) -> Run:
    row = (
        await session.execute(sa.select(Run).where(Run.id == run_id, engine.tenant_clause(principal.tenant_id)))
    ).scalar_one_or_none()
    if row is None or row.workflow not in definitions.WORKFLOWS or not _allowed(principal, row.workflow):
        raise NotFoundError("workflow run not found")
    return row


def _out(row: Run) -> RunOut:
    return RunOut.model_validate(row, from_attributes=True)


@router.get("/runs", response_model=list[RunOut])
async def list_runs(
    session: SessionDep,
    principal: CurrentPrincipal,
    workflow: str | None = None,
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[RunOut]:
    names = _readable(principal)
    if workflow is not None:
        names = [n for n in names if n == workflow]
    stmt = sa.select(Run).where(Run.workflow.in_(names), engine.tenant_clause(principal.tenant_id))
    if status is not None:
        stmt = stmt.where(Run.status == status)
    rows = (await session.execute(stmt.order_by(Run.created_at.desc(), Run.id).limit(limit))).scalars()
    return [_out(r) for r in rows]


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: uuid.UUID, session: SessionDep, principal: CurrentPrincipal) -> RunDetail:
    row = await _own_run(session, principal, run_id)
    steps = (
        await session.execute(
            sa.select(StepRecord).where(StepRecord.run_id == run_id).order_by(StepRecord.finished_at, StepRecord.step)
        )
    ).scalars()
    return RunDetail(**_out(row).model_dump(), steps=[StepOut.model_validate(s, from_attributes=True) for s in steps])


@router.post("/runs/{run_id}/cancel", response_model=RunOut, status_code=202)
async def cancel_run(run_id: uuid.UUID, session: SessionDep, principal: CurrentPrincipal) -> RunOut:
    await _own_run(session, principal, run_id)
    row = await engine.cancel(session, run_id, principal.tenant_id)
    if row is None:
        raise NotFoundError("workflow run not found")
    await session.commit()
    return _out(row)


@router.post("/{name}/runs", response_model=RunOut, status_code=202)
async def start_run(name: str, body: StartIn, session: SessionDep, principal: CurrentPrincipal) -> RunOut:
    if name not in definitions.WORKFLOWS:
        raise NotFoundError("unknown workflow")
    if not _allowed(principal, name):
        raise AppError("forbidden", "you do not have permission to do that", 403)
    try:
        run_id = await engine.start(
            name,
            body.input,
            session=session,
            tenant_id=principal.tenant_id,
            created_by=principal.user_id,
            dedupe_key=body.idempotency_key,
        )
    except ValueError as exc:
        raise AppError("validation_error", str(exc), 422) from exc
    await session.commit()
    row = (await session.execute(sa.select(Run).where(Run.id == run_id))).scalar_one()
    return _out(row)
