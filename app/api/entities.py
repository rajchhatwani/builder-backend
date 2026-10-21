import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination, pagination
from app.db import get_session
from app.schemas.common import Page
from app.schemas.entity import EntityCreate, EntityRead, EntityUpdate
from app.services.entity_service import EntityService

router = APIRouter(tags=["entities"])


@router.post(
    "/projects/{project_id}/entities",
    response_model=EntityRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_entity(
    project_id: uuid.UUID, body: EntityCreate, session: AsyncSession = Depends(get_session)
) -> EntityRead:
    entity = await EntityService(session).create(project_id, body)
    return EntityRead.model_validate(entity)


@router.get("/projects/{project_id}/entities", response_model=Page[EntityRead])
async def list_entities(
    project_id: uuid.UUID,
    page: Pagination = Depends(pagination),
    session: AsyncSession = Depends(get_session),
) -> Page[EntityRead]:
    entities, total = await EntityService(session).list(project_id, page.limit, page.offset)
    return Page[EntityRead](
        items=[EntityRead.model_validate(e) for e in entities],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/entities/{entity_id}", response_model=EntityRead)
async def get_entity(
    entity_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> EntityRead:
    entity = await EntityService(session).get(entity_id)
    return EntityRead.model_validate(entity)


@router.patch("/entities/{entity_id}", response_model=EntityRead)
async def update_entity(
    entity_id: uuid.UUID, body: EntityUpdate, session: AsyncSession = Depends(get_session)
) -> EntityRead:
    entity = await EntityService(session).update(entity_id, body)
    return EntityRead.model_validate(entity)


@router.delete("/entities/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entity(entity_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    await EntityService(session).delete(entity_id)
