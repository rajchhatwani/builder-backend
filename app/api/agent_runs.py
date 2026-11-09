"""Builder-agent runs (B3-1). Editors write (platform_authz default); viewers read.

POST /projects/{project_id}/agent/runs                     create (editor, verified e-mail)
GET  /projects/{project_id}/agent/runs                     list (viewer)
GET  /projects/{project_id}/agent/runs/{run_id}            read with steps, paged (viewer)
POST /projects/{project_id}/agent/runs/{run_id}/cancel     cancel (editor)
POST /projects/{project_id}/agent/runs/{run_id}/pause      pause a live run at its next step (editor)
POST /projects/{project_id}/agent/runs/{run_id}/resume     drive / re-drive; lifts a pause (editor, verified e-mail)
POST /projects/{project_id}/agent/runs/{run_id}/gates      run the platform gates over the draft (editor)
"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination, pagination, require_verified_email
from app.db import get_session
from app.schemas.agent_run import GateRunResult, RunCreate, RunDetail, RunRead
from app.schemas.common import Page
from app.services.access_service import Principal
from app.services.agent.run_service import AgentDeps, RunService, get_agent_deps

router = APIRouter(prefix="/projects/{project_id}/agent/runs", tags=["agent"])


def agent_deps() -> AgentDeps:
    """Overridable: the toolbox, approvals service and model-provider factory."""
    return get_agent_deps()


@router.post("", response_model=RunRead, status_code=201)
async def create_run(
    project_id: uuid.UUID,
    body: RunCreate,
    principal: Principal = Depends(require_verified_email),
    db: AsyncSession = Depends(get_session),
) -> RunRead:
    run = await RunService(db).create(project_id, principal.user.id, body.goal, body.workspace_id)
    return RunRead.model_validate(run)


@router.get("", response_model=Page[RunRead])
async def list_runs(
    project_id: uuid.UUID,
    page: Pagination = Depends(pagination),
    db: AsyncSession = Depends(get_session),
) -> Page[RunRead]:
    rows, total = await RunService(db).list_runs(project_id, page.limit, page.offset)
    return Page[RunRead](
        items=[RunRead.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_session),
) -> RunDetail:
    return await RunService(db).detail(project_id, run_id, limit, offset)


@router.post("/{run_id}/cancel", response_model=RunRead)
async def cancel_run(
    project_id: uuid.UUID, run_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> RunRead:
    return RunRead.model_validate(await RunService(db).cancel(project_id, run_id))


@router.post("/{run_id}/pause", response_model=RunRead)
async def pause_run(
    project_id: uuid.UUID, run_id: uuid.UUID, db: AsyncSession = Depends(get_session)
) -> RunRead:
    return RunRead.model_validate(await RunService(db).pause(project_id, run_id))


@router.post("/{run_id}/gates", response_model=GateRunResult)
async def run_gates(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    deps: AgentDeps = Depends(agent_deps),
    db: AsyncSession = Depends(get_session),
) -> GateRunResult:
    return GateRunResult(**await RunService(db).run_gates(project_id, run_id, deps))


@router.post(
    "/{run_id}/resume",
    response_model=RunRead,
    dependencies=[Depends(require_verified_email)],
)
async def resume_run(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    deps: AgentDeps = Depends(agent_deps),
    db: AsyncSession = Depends(get_session),
) -> RunRead:
    run = await RunService(db).resume(project_id, run_id, deps)
    return RunRead.model_validate(run)
