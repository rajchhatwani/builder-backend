import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination, pagination
from app.db import get_session
from app.schemas.common import Page
from app.schemas.field import FieldCreate, FieldRead, FieldUpdate
from app.services.field_service import FieldService

router = APIRouter(tags=["fields"])


@router.post(
    "/entities/{entity_id}/fields", response_model=FieldRead, status_code=status.HTTP_201_CREATED
)
async def create_field(
    entity_id: uuid.UUID, body: FieldCreate, session: AsyncSession = Depends(get_session)
) -> FieldRead:
    field = await FieldService(session).create(entity_id, body)
    return FieldRead.model_validate(field)


@router.get("/entities/{entity_id}/fields", response_model=Page[FieldRead])
async def list_fields(
    entity_id: uuid.UUID,
    page: Pagination = Depends(pagination),
    session: AsyncSession = Depends(get_session),
) -> Page[FieldRead]:
    fields, total = await FieldService(session).list(entity_id, page.limit, page.offset)
    return Page[FieldRead](
        items=[FieldRead.model_validate(f) for f in fields],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.patch("/fields/{field_id}", response_model=FieldRead)
async def update_field(
    field_id: uuid.UUID, body: FieldUpdate, session: AsyncSession = Depends(get_session)
) -> FieldRead:
    field = await FieldService(session).update(field_id, body)
    return FieldRead.model_validate(field)


@router.delete("/fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_field(field_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    await FieldService(session).delete(field_id)
