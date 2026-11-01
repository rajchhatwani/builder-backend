"""Database side of each registry operation: calls the existing services, nothing re-implemented.

Every function runs inside an `OpScope` in explicit mode, where the services' own `commit()`
calls only flush, so the spec write and the op-log row land in one transaction.
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.spec_models import Spec
from app.exceptions import AppError
from app.models.auth_config import ProjectAuthConfig
from app.models.auth_custom_field import AuthCustomField
from app.models.authorization_config import ProjectAuthorization
from app.models.behavior_config import ProjectBehavior
from app.models.deployment_config import ProjectDeployment
from app.models.documents_config import ProjectDocuments
from app.models.entity import Entity
from app.models.field import Field
from app.models.keycloak_config import ProjectKeycloakConfig
from app.models.observability_config import ProjectObservability
from app.models.payments_config import ProjectPaymentsConfig
from app.models.project_permission import ProjectPermission
from app.models.project_role import ProjectRole
from app.models.relation import Relation
from app.models.storage_config import ProjectStorageConfig
from app.schemas.entity import EntityCreate, EntityOptions, EntityUpdate
from app.schemas.field import FieldCreate, FieldUpdate
from app.schemas.relation import RelationCreate, RelationUpdate
from app.services.behavior_service import BLOCKS, apply_section
from app.services.entity_service import EntityService
from app.services.field_service import FieldService
from app.services.ops import registry as r
from app.services.relation_service import RelationService
from app.services.spec_service import SpecService

DbApply = Callable[[AsyncSession, uuid.UUID, Any], Awaitable[Any]]


async def _entity(s: AsyncSession, pid: uuid.UUID, name: str) -> Entity:
    row = (
        await s.execute(select(Entity).where(Entity.project_id == pid, Entity.name == name))
    ).scalar_one_or_none()
    if row is None:
        raise AppError(code="not_found", message=f"entity '{name}' not found", status_code=404)
    return row


async def _field(s: AsyncSession, entity: Entity, name: str) -> Field:
    row = (
        await s.execute(select(Field).where(Field.entity_id == entity.id, Field.name == name))
    ).scalar_one_or_none()
    if row is None:
        raise AppError(code="not_found", message=f"field '{name}' not found", status_code=404)
    return row


async def _relation(s: AsyncSession, pid: uuid.UUID, frm: str, name: str, to: str) -> Relation:
    a, b = await _entity(s, pid, frm), await _entity(s, pid, to)
    row = (
        await s.execute(
            select(Relation).where(
                Relation.project_id == pid,
                Relation.from_entity_id == a.id,
                Relation.to_entity_id == b.id,
                Relation.from_name == name,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppError(code="not_found", message="relation not found", status_code=404)
    return row


async def add_entity(s: AsyncSession, pid: uuid.UUID, p: r.AddEntity) -> Entity:
    e = p.entity.resolved()
    entity = await EntityService(s).create(
        pid,
        EntityCreate(
            name=e.name,
            table_name=e.table_name,
            plural_path=e.plural_path,
            options=EntityOptions(**e.options.model_dump()),
        ),
    )
    for f in e.fields:
        await FieldService(s).create(entity.id, FieldCreate(**f.model_dump(), position=None))
    return entity


async def update_entity(s: AsyncSession, pid: uuid.UUID, p: r.UpdateEntity) -> Entity:
    entity = await _entity(s, pid, p.name)
    return await EntityService(s).update(entity.id, EntityUpdate(**p.changes))


async def remove_entity(s: AsyncSession, pid: uuid.UUID, p: r.RemoveEntity) -> None:
    await EntityService(s).delete((await _entity(s, pid, p.name)).id)


async def add_field(s: AsyncSession, pid: uuid.UUID, p: r.AddField) -> Field:
    entity = await _entity(s, pid, p.entity)
    created = await FieldService(s).create(
        entity.id, FieldCreate(**p.field.model_dump(), position=None)
    )
    if p.index is not None:
        await s.flush()
        rows = list(
            (
                await s.execute(
                    select(Field)
                    .where(Field.entity_id == entity.id)
                    .order_by(Field.position, Field.name)
                )
            ).scalars()
        )
        rows.remove(created)
        rows.insert(min(p.index, len(rows)), created)
        for i, row in enumerate(rows):
            row.position = i
    return created


async def update_field(s: AsyncSession, pid: uuid.UUID, p: r.UpdateField) -> Field:
    field = await _field(s, await _entity(s, pid, p.entity), p.name)
    return await FieldService(s).update(field.id, FieldUpdate(**p.changes))


async def remove_field(s: AsyncSession, pid: uuid.UUID, p: r.RemoveField) -> None:
    await FieldService(s).delete((await _field(s, await _entity(s, pid, p.entity), p.name)).id)


async def add_relation(s: AsyncSession, pid: uuid.UUID, p: r.AddRelation) -> Relation:
    rel = p.relation
    return await RelationService(s).create(
        pid,
        RelationCreate(
            kind=rel.kind,  # type: ignore[arg-type]
            from_entity_id=(await _entity(s, pid, rel.from_entity)).id,
            to_entity_id=(await _entity(s, pid, rel.to_entity)).id,
            from_name=rel.from_name,
            to_name=rel.to_name,
            on_delete=rel.on_delete,  # type: ignore[arg-type]
            required=rel.required,
        ),
    )


async def update_relation(s: AsyncSession, pid: uuid.UUID, p: r.UpdateRelation) -> Relation:
    row = await _relation(s, pid, p.from_entity, p.from_name, p.to_entity)
    return await RelationService(s).update(row.id, RelationUpdate(**p.changes))


async def remove_relation(s: AsyncSession, pid: uuid.UUID, p: r.RemoveRelation) -> None:
    row = await _relation(s, pid, p.from_entity, p.from_name, p.to_entity)
    await RelationService(s).delete(row.id)


async def set_section(s: AsyncSession, pid: uuid.UUID, p: r.SetSection) -> None:
    items = r.section_adapter(p.section).validate_python(p.items)
    await SpecService(s)._replace_behavior_section(pid, p.section, items)  # noqa: SLF001


_BLOCK_TABLES: dict[str, tuple[type[Any], ...]] = {
    "auth": (
        ProjectPermission,
        ProjectRole,
        AuthCustomField,
        ProjectKeycloakConfig,
        ProjectAuthConfig,
    ),
    "payments": (ProjectPaymentsConfig,),
    "storage": (ProjectStorageConfig,),
    "authorization": (ProjectAuthorization,),
    "observability": (ProjectObservability,),
    "deployment": (ProjectDeployment,),
    "documents": (ProjectDocuments,),
}


async def replace_spec(s: AsyncSession, pid: uuid.UUID, p: r.ReplaceSpec) -> None:
    """Make the project's spec equal `p.spec` exactly. `SpecService.replace` leaves a block
    alone when the spec omits it; going back to an earlier state must remove it, so blocks
    (and behaviour sections) the target lacks are cleared first. Credentials are not in a
    spec and are never touched."""
    spec: Spec = p.spec
    for block, tables in _BLOCK_TABLES.items():
        if getattr(spec, block) is None:
            for model in tables:
                await s.execute(delete(model).where(model.project_id == pid))
    row = (
        await s.execute(select(ProjectBehavior).where(ProjectBehavior.project_id == pid))
    ).scalar_one_or_none()
    if row is not None:
        for section in r.SECTIONS:
            if not getattr(spec, section) and row.sections.get(section):
                apply_section(row, section, [])
        for block in BLOCKS:
            if getattr(spec, block) is None and row.sections.get(block) is not None:
                apply_section(row, block, None)
    await SpecService(s).replace(pid, spec, validate_spec=False)


DB_APPLY: dict[str, DbApply] = {
    "add_entity": add_entity,
    "update_entity": update_entity,
    "remove_entity": remove_entity,
    "add_field": add_field,
    "update_field": update_field,
    "remove_field": remove_field,
    "add_relation": add_relation,
    "update_relation": update_relation,
    "remove_relation": remove_relation,
    "set_section": set_section,
    "replace_spec": replace_spec,
}


async def run(s: AsyncSession, pid: uuid.UUID, op_type: str, payload: BaseModel) -> Any:
    return await DB_APPLY[op_type](s, pid, payload)
