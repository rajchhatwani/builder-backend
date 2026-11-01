import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.security import forbidden
from app.db import get_session
from app.models.enums import MemberRole
from app.services.access_service import ROLE_LEVEL
from app.schemas.migration_plan import MigrationPlanRequest, MigrationPlanResponse
from app.services.generation_service import GenerationService

router = APIRouter(tags=["generate"])


@router.post("/projects/{project_id}/migration-plan", response_model=MigrationPlanResponse)
async def migration_plan(
    request: Request,
    project_id: uuid.UUID,
    body: MigrationPlanRequest | None = None,
    accept_unreadable_baseline: bool = Query(
        False, description="Plan against an empty spec if the baseline snapshot is unreadable."
    ),
    session: AsyncSession = Depends(get_session),
) -> MigrationPlanResponse:
    """Plan the database change from the last generation (or `against_generation_id`) to the
    current spec. Read-only; needs the editor role (the default for a POST)."""
    if (
        accept_unreadable_baseline
        and ROLE_LEVEL[request.state.member_role] < ROLE_LEVEL[MemberRole.editor]
    ):
        raise forbidden("only an editor or owner can accept an unreadable baseline")
    return await GenerationService(session).migration_plan(
        project_id, body or MigrationPlanRequest(), accept_unreadable_baseline
    )
