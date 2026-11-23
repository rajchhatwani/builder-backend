"""Suite identity routes: the join impact report and the migration state (path b).

    GET /projects/{id}/suite/join/impact     spec-level impact report            (viewer)
    PUT /projects/{id}/suite/migration       move the migration state forward    (editor)
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas.suite import SuiteJoinImpact, SuiteMigrationRead, SuiteMigrationWrite
from app.services.suite_migration_service import SuiteMigrationService

router = APIRouter(prefix="/projects/{project_id}/suite", tags=["suite"])


@router.get(
    "/join/impact",
    response_model=SuiteJoinImpact,
    summary="What moving this app under its suite hub would change (spec level)",
)
async def join_impact(
    project_id: uuid.UUID,
    workspace_id: uuid.UUID | None = None,
    session: AsyncSession = Depends(get_session),
) -> SuiteJoinImpact:
    return await SuiteMigrationService(session).impact(project_id, workspace_id)


@router.put(
    "/migration",
    response_model=SuiteMigrationRead,
    summary="Move the suite migration forward (legacy_read_only, dual, hub_only)",
)
async def put_migration(
    project_id: uuid.UUID,
    body: SuiteMigrationWrite,
    session: AsyncSession = Depends(get_session),
) -> SuiteMigrationRead:
    return await SuiteMigrationService(session).put_migration(project_id, body)
