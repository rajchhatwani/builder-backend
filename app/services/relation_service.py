import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AppError
from app.models.entity import Entity
from app.models.project import Project
from app.models.relation import Relation
from app.schemas.relation import RelationCreate, RelationUpdate


def _relation_conflict() -> AppError:
    return AppError(
        code="conflict",
        message="a relation with this from_entity/to_entity/from_name already exists",
        status_code=409,
    )


class RelationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _get_project_or_404(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise AppError(code="not_found", message="project not found", status_code=404)
        return project

    async def _get_relation_or_404(self, relation_id: uuid.UUID) -> Relation:
        relation = await self.session.get(Relation, relation_id)
        if relation is None:
            raise AppError(code="not_found", message="relation not found", status_code=404)
        return relation

    async def _require_entity_in_project(
        self, project_id: uuid.UUID, entity_id: uuid.UUID, label: str
    ) -> None:
        entity = await self.session.get(Entity, entity_id)
        if entity is None or entity.project_id != project_id:
            raise AppError(
                code="invalid_reference",
                message=f"{label} does not reference an entity in this project",
                status_code=400,
            )

    async def create(self, project_id: uuid.UUID, data: RelationCreate) -> Relation:
        await self._get_project_or_404(project_id)
        await self._require_entity_in_project(project_id, data.from_entity_id, "from_entity_id")
        await self._require_entity_in_project(project_id, data.to_entity_id, "to_entity_id")
        relation = Relation(
            project_id=project_id,
            kind=data.kind,
            from_entity_id=data.from_entity_id,
            to_entity_id=data.to_entity_id,
            from_name=data.from_name,
            to_name=data.to_name,
            on_delete=data.on_delete,
            required=data.required,
        )
        self.session.add(relation)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise _relation_conflict() from exc
        return relation

    async def list(
        self, project_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[Relation], int]:
        await self._get_project_or_404(project_id)
        total = (
            await self.session.execute(
                select(func.count()).select_from(Relation).where(Relation.project_id == project_id)
            )
        ).scalar_one()
        rows = (
            await self.session.execute(
                select(Relation)
                .where(Relation.project_id == project_id)
                .order_by(Relation.created_at)
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
        return list(rows), total

    async def update(self, relation_id: uuid.UUID, data: RelationUpdate) -> Relation:
        relation = await self._get_relation_or_404(relation_id)
        updates = data.model_dump(exclude_unset=True)
        for key, value in updates.items():
            setattr(relation, key, value)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise _relation_conflict() from exc
        return relation

    async def delete(self, relation_id: uuid.UUID) -> None:
        relation = await self._get_relation_or_404(relation_id)
        await self.session.delete(relation)
        await self.session.commit()
