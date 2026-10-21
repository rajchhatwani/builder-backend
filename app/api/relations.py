import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination, pagination
from app.db import get_session
from app.schemas.common import Page
from app.schemas.relation import RelationCreate, RelationRead, RelationUpdate
from app.services.relation_service import RelationService

router = APIRouter(tags=["relations"])


@router.post(
    "/projects/{project_id}/relations",
    response_model=RelationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_relation(
    project_id: uuid.UUID, body: RelationCreate, session: AsyncSession = Depends(get_session)
) -> RelationRead:
    relation = await RelationService(session).create(project_id, body)
    return RelationRead.model_validate(relation)


@router.get("/projects/{project_id}/relations", response_model=Page[RelationRead])
async def list_relations(
    project_id: uuid.UUID,
    page: Pagination = Depends(pagination),
    session: AsyncSession = Depends(get_session),
) -> Page[RelationRead]:
    relations, total = await RelationService(session).list(project_id, page.limit, page.offset)
    return Page[RelationRead](
        items=[RelationRead.model_validate(r) for r in relations],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.patch("/relations/{relation_id}", response_model=RelationRead)
async def update_relation(
    relation_id: uuid.UUID, body: RelationUpdate, session: AsyncSession = Depends(get_session)
) -> RelationRead:
    relation = await RelationService(session).update(relation_id, body)
    return RelationRead.model_validate(relation)


@router.delete("/relations/{relation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_relation(
    relation_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> None:
    await RelationService(session).delete(relation_id)
