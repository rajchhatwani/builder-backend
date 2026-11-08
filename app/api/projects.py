import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination, pagination
from app.api.security import guard
from app.db import get_session
from app.models.platform import Organization
from app.schemas.common import Page
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services.access_service import Principal
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    principal: Principal = Depends(guard),
    session: AsyncSession = Depends(get_session),
) -> ProjectRead:
    project = await ProjectService(session).create(
        body, principal.user, organization_id=body.organization_id
    )
    return ProjectRead.model_validate(project)


@router.get("", response_model=Page[ProjectRead])
async def list_projects(
    page: Pagination = Depends(pagination),
    principal: Principal = Depends(guard),
    session: AsyncSession = Depends(get_session),
) -> Page[ProjectRead]:
    projects, total = await ProjectService(session).list(
        principal.user.id,
        page.limit,
        page.offset,
        principal.token_project_id,
        principal.impersonation.organization_id if principal.impersonation else None,
    )
    org_ids = {p.organization_id for p in projects}
    rows = await session.execute(
        select(Organization.id, Organization.deletion_scheduled_for).where(
            Organization.id.in_(org_ids), Organization.deletion_requested_at.is_not(None)
        )
    )
    locked = {org_id: scheduled for org_id, scheduled in rows.all()}
    items = []
    for p in projects:
        item = ProjectRead.model_validate(p)
        if p.organization_id in locked:
            item.organization_locked = True
            item.organization_deletion_scheduled_for = locked[p.organization_id]
        items.append(item)
    return Page[ProjectRead](
        items=items,
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> ProjectRead:
    project = await ProjectService(session).get(project_id)
    return ProjectRead.model_validate(project)


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: uuid.UUID, body: ProjectUpdate, session: AsyncSession = Depends(get_session)
) -> ProjectRead:
    project = await ProjectService(session).update(project_id, body)
    return ProjectRead.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> None:
    await ProjectService(session).delete(project_id)
