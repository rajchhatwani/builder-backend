"""Routes for the cloud deployment settings of a project."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas.deployment import DeploymentIssues, DeploymentPlan, DeploymentRead, DeploymentWrite
from app.services.deployment_service import DeploymentService
from app.services.spec_service import SpecService

router = APIRouter(prefix="/projects/{project_id}/deployment", tags=["deployment"])


@router.get(
    "",
    response_model=DeploymentRead,
    summary="Get the deployment settings (defaults, switched off, when never saved)",
)
async def get_deployment(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> DeploymentRead:
    return await DeploymentService(session).get(project_id)


@router.put("", response_model=DeploymentRead, summary="Create or replace the settings")
async def put_deployment(
    project_id: uuid.UUID,
    body: DeploymentWrite,
    session: AsyncSession = Depends(get_session),
) -> DeploymentRead:
    return await DeploymentService(session).put(project_id, body)


@router.get(
    "/issues",
    response_model=DeploymentIssues,
    summary="Problems with the deployment settings (no side effects)",
)
async def deployment_issues(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> DeploymentIssues:
    await DeploymentService(session).get(project_id)  # 404 for an unknown project
    found = await SpecService(session).validate(project_id)
    return DeploymentIssues(
        issues=[i.model_dump() for i in found if i.path.startswith("deployment")]
    )


@router.post(
    "/plan",
    response_model=DeploymentPlan,
    summary="Turn settings (saved or not) into concrete numbers and tfvars, without saving",
)
async def deployment_plan(project_id: uuid.UUID, body: DeploymentWrite) -> DeploymentPlan:
    return DeploymentService.preview(body)
