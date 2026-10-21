import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AppError
from app.models.entity import Entity
from app.models.field import Field
from app.schemas.field import FieldCreate, FieldUpdate


def _name_conflict() -> AppError:
    return AppError(
        code="conflict",
        message="a field with this name already exists on this entity",
        status_code=409,
    )


class FieldService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _get_entity_or_404(self, entity_id: uuid.UUID) -> Entity:
        entity = await self.session.get(Entity, entity_id)
        if entity is None:
            raise AppError(code="not_found", message="entity not found", status_code=404)
        return entity

    async def _get_field_or_404(self, field_id: uuid.UUID) -> Field:
        field = await self.session.get(Field, field_id)
        if field is None:
            raise AppError(code="not_found", message="field not found", status_code=404)
        return field

    async def create(self, entity_id: uuid.UUID, data: FieldCreate) -> Field:
        await self._get_entity_or_404(entity_id)
        position = data.position
        if position is None:
            max_position = (
                await self.session.execute(
                    select(func.max(Field.position)).where(Field.entity_id == entity_id)
                )
            ).scalar_one_or_none()
            position = 0 if max_position is None else max_position + 1
        field = Field(
            entity_id=entity_id,
            name=data.name,
            type=data.type,
            required=data.required,
            unique=data.unique,
            indexed=data.indexed,
            default=data.default,
            max_length=data.max_length,
            min_value=data.min_value,
            max_value=data.max_value,
            enum_values=data.enum_values,
            position=position,
        )
        self.session.add(field)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise _name_conflict() from exc
        return field

    async def list(self, entity_id: uuid.UUID, limit: int, offset: int) -> tuple[list[Field], int]:
        await self._get_entity_or_404(entity_id)
        total = (
            await self.session.execute(
                select(func.count()).select_from(Field).where(Field.entity_id == entity_id)
            )
        ).scalar_one()
        rows = (
            await self.session.execute(
                select(Field)
                .where(Field.entity_id == entity_id)
                .order_by(Field.position)
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
        return list(rows), total

    async def update(self, field_id: uuid.UUID, data: FieldUpdate) -> Field:
        field = await self._get_field_or_404(field_id)
        updates = data.model_dump(exclude_unset=True)
        for key, value in updates.items():
            setattr(field, key, value)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise _name_conflict() from exc
        return field

    async def delete(self, field_id: uuid.UUID) -> None:
        field = await self._get_field_or_404(field_id)
        await self.session.delete(field)
        await self.session.commit()
