import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.naming import pluralize, to_snake_case
from app.exceptions import AppError
from app.models.entity import Entity
from app.models.project import Project
from app.schemas.entity import EntityCreate, EntityUpdate


def _name_conflict() -> AppError:
    return AppError(
        code="conflict",
        message="an entity with this name, table name or plural path already exists",
        status_code=409,
    )


class EntityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _get_project_or_404(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise AppError(code="not_found", message="project not found", status_code=404)
        return project

    async def create(self, project_id: uuid.UUID, data: EntityCreate) -> Entity:
        await self._get_project_or_404(project_id)
        # Plural by default: a singular table name like `user` is a reserved word in Postgres.
        default_plural = pluralize(to_snake_case(data.name))
        entity = Entity(
            project_id=project_id,
            name=data.name,
            table_name=data.table_name or default_plural,
            plural_path=data.plural_path or default_plural,
            options=data.options.model_dump(),
        )
        self.session.add(entity)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise _name_conflict() from exc
        return entity

    async def list(
        self, project_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[Entity], int]:
        await self._get_project_or_404(project_id)
        total = (
            await self.session.execute(
                select(func.count()).select_from(Entity).where(Entity.project_id == project_id)
            )
        ).scalar_one()
        rows = (
            await self.session.execute(
                select(Entity)
                .where(Entity.project_id == project_id)
                .order_by(Entity.created_at)
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
        return list(rows), total

    async def get(self, entity_id: uuid.UUID) -> Entity:
        entity = await self.session.get(Entity, entity_id)
        if entity is None:
            raise AppError(code="not_found", message="entity not found", status_code=404)
        return entity

    async def update(self, entity_id: uuid.UUID, data: EntityUpdate) -> Entity:
        entity = await self.get(entity_id)
        updates = data.model_dump(exclude_unset=True)
        for key, value in updates.items():
            setattr(entity, key, value)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise _name_conflict() from exc
        return entity

    async def delete(self, entity_id: uuid.UUID) -> None:
        entity = await self.get(entity_id)
        await self.session.delete(entity)
        await self.session.commit()
