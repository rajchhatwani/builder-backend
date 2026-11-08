"""Routes for the observability (OpenTelemetry) settings of a project."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas.observability import ObservabilityIssues, ObservabilityRead, ObservabilityWrite
from app.services.observability_service import ObservabilityService
from app.services.spec_service import SpecService

router = APIRouter(prefix="/projects/{project_id}/observability", tags=["observability"])


@router.get(
    "",
    response_model=ObservabilityRead,
    summary="Get the observability settings (defaults, switched off, when never saved)",
)
async def get_observability(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> ObservabilityRead:
    return await ObservabilityService(session).get(project_id)


@router.put("", response_model=ObservabilityRead, summary="Create or replace the settings")
async def put_observability(
    project_id: uuid.UUID,
    body: ObservabilityWrite,
    session: AsyncSession = Depends(get_session),
) -> ObservabilityRead:
    return await ObservabilityService(session).put(project_id, body)


@router.get(
    "/issues",
    response_model=ObservabilityIssues,
    summary="Problems with the observability settings (no side effects)",
)
async def observability_issues(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> ObservabilityIssues:
    await ObservabilityService(session).get(project_id)  # 404 for an unknown project
    found = await SpecService(session).validate(project_id)
    return ObservabilityIssues(
        issues=[i.model_dump() for i in found if i.path.startswith("observability")]
    )
