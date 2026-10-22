import uuid

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DbEngine, FieldType, OnDelete, RelationKind
from app.core.spec_models import (
    Spec,
    SpecEntity,
    SpecEntityOptions,
    SpecField,
    SpecProject,
    SpecRelation,
)
from app.core.validation import ValidationIssue, validate
from app.exceptions import AppError
from app.models.entity import Entity
from app.models.field import Field
from app.models.project import Project
from app.models.relation import Relation


class SpecService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _get_project_or_404(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise AppError(code="not_found", message="project not found", status_code=404)
        return project

    async def assemble(self, project_id: uuid.UUID) -> Spec:
        """Build the spec from the normalized tables. Ordering is fully deterministic:
        entities by name, fields by position, relations by (from entity, from_name, to entity)."""
        project = await self._get_project_or_404(project_id)
        entities = list(
            (
                await self.session.execute(
                    select(Entity).where(Entity.project_id == project_id).order_by(Entity.name)
                )
            ).scalars()
        )
        names_by_id = {e.id: e.name for e in entities}
        fields = (
            await self.session.execute(
                select(Field)
                .where(Field.entity_id.in_(names_by_id))
                .order_by(Field.position, Field.name)
            )
        ).scalars()
        fields_by_entity: dict[uuid.UUID, list[SpecField]] = {e.id: [] for e in entities}
        for f in fields:
            fields_by_entity[f.entity_id].append(
                SpecField(
                    name=f.name,
                    type=f.type.value,
                    required=f.required,
                    unique=f.unique,
                    indexed=f.indexed,
                    default=f.default,
                    max_length=f.max_length,
                    min_value=f.min_value,
                    max_value=f.max_value,
                    enum_values=f.enum_values,
                )
            )
        relations = (
            await self.session.execute(select(Relation).where(Relation.project_id == project_id))
        ).scalars()
        spec_relations = sorted(
            (
                SpecRelation(
                    kind=r.kind.value,
                    from_entity=names_by_id[r.from_entity_id],
                    to_entity=names_by_id[r.to_entity_id],
                    from_name=r.from_name,
                    to_name=r.to_name,
                    on_delete=r.on_delete.value,
                    required=r.required,
                )
                for r in relations
            ),
            key=lambda r: (r.from_entity, r.from_name, r.to_entity),
        )
        return Spec(
            project=SpecProject(
                name=project.name,
                slug=project.slug,
                description=project.description,
                db_engine=project.db_engine.value,
            ),
            entities=[
                SpecEntity(
                    name=e.name,
                    table_name=e.table_name,
                    plural_path=e.plural_path,
                    options=SpecEntityOptions.model_validate(e.options),
                    fields=fields_by_entity[e.id],
                )
                for e in entities
            ],
            relations=spec_relations,
        )

    async def validate(self, project_id: uuid.UUID) -> list[ValidationIssue]:
        return validate(await self.assemble(project_id))

    async def replace(self, project_id: uuid.UUID, spec: Spec) -> Spec:
        """Replace the project's entities, fields and relations with the spec's.

        The project's own identity (name, slug, description) is left alone: a spec
        exported from one project can be imported into another without a slug clash.
        All-or-nothing: an invalid spec changes nothing.
        """
        project = await self._get_project_or_404(project_id)
        issues = validate(spec)
        if issues:
            raise AppError(
                code="spec_invalid",
                message=f"spec has {len(issues)} validation issue(s)",
                status_code=422,
                details=[issue.model_dump() for issue in issues],
            )

        await self.session.execute(
            delete(Relation).where(Relation.project_id == project_id),
            execution_options={"synchronize_session": False},
        )
        await self.session.execute(
            delete(Entity).where(Entity.project_id == project_id),
            execution_options={"synchronize_session": False},
        )

        ids_by_name: dict[str, uuid.UUID] = {}
        for spec_entity in spec.entities:
            entity = Entity(
                id=uuid.uuid4(),
                project_id=project_id,
                name=spec_entity.name,
                table_name=spec_entity.table_name,
                plural_path=spec_entity.plural_path,
                options=spec_entity.options.model_dump(),
            )
            ids_by_name[entity.name] = entity.id
            self.session.add(entity)
            for position, f in enumerate(spec_entity.fields):
                self.session.add(
                    Field(
                        entity_id=entity.id,
                        name=f.name,
                        type=FieldType(f.type),
                        required=f.required,
                        unique=f.unique,
                        indexed=f.indexed,
                        default=f.default,
                        max_length=f.max_length,
                        min_value=f.min_value,
                        max_value=f.max_value,
                        enum_values=f.enum_values,
                        position=position,
                    )
                )
        # Entities must exist before fields/relations reference them.
        await self.session.flush()
        for r in spec.relations:
            self.session.add(
                Relation(
                    project_id=project_id,
                    kind=RelationKind(r.kind),
                    from_entity_id=ids_by_name[r.from_entity],
                    to_entity_id=ids_by_name[r.to_entity],
                    from_name=r.from_name,
                    to_name=r.to_name,
                    on_delete=OnDelete(r.on_delete),
                    required=r.required,
                )
            )
        project.db_engine = DbEngine(spec.project.db_engine)
        project.version += 1
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppError(
                code="conflict", message="spec conflicts with existing data", status_code=409
            ) from exc
        return await self.assemble(project_id)
