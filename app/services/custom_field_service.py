"""Per-row custom fields over the typed ops (CP4F2-B): every write goes through the ops service
so history, undo, the access diff and the migration planner all see it."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.custom_fields import (
    CustomFieldError,
    PromoteProblem,
    check_promotable,
    is_proven,
    promote,
)
from app.core.spec_models import Spec, SpecCustomFieldDef, SpecEntity
from app.exceptions import AppError
from app.schemas.custom_fields import (
    CustomFieldDef,
    CustomFieldList,
    MigrationStepRead,
    PromoteCheckResult,
    PromoteProblemRead,
    PromoteResult,
)
from app.services.migration_planner import plan_migration
from app.services.ops.scope import Actor
from app.services.ops.service import OpsService
from app.services.spec_service import SpecService


def _entity(spec: Spec, name: str) -> SpecEntity:
    for e in spec.entities:
        if e.name == name:
            return e
    raise AppError("not_found", "entity not found", 404)


def _def_read(d: SpecCustomFieldDef) -> CustomFieldDef:
    return CustomFieldDef(**d.model_dump())


def _unavailable(problems: list[PromoteProblem]) -> AppError:
    return AppError("custom_field_promote_unavailable", problems[0].message, 409)


class CustomFieldService:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def _spec(self, project_id: uuid.UUID) -> Spec:
        return await SpecService(self.s).assemble(project_id)

    async def _get(self, project_id: uuid.UUID, entity: str, name: str) -> CustomFieldDef:
        e = _entity(await self._spec(project_id), entity)
        for d in e.custom_fields.defs if e.custom_fields else []:
            if d.name == name:
                return _def_read(d)
        raise AppError("not_found", "custom field not found", 404)

    async def list_defs(self, project_id: uuid.UUID, entity: str) -> CustomFieldList:
        e = _entity(await self._spec(project_id), entity)
        cf = e.custom_fields
        return CustomFieldList(
            entity=e.name,
            enabled=bool(cf and cf.enabled),
            max_keys=cf.max_keys if cf else 50,
            max_bytes=cf.max_bytes if cf else 8192,
            items=[_def_read(d) for d in (cf.defs if cf else [])],
        )

    async def define(
        self, project_id: uuid.UUID, entity: str, body: CustomFieldDef, actor: Actor
    ) -> CustomFieldDef:
        _entity(await self._spec(project_id), entity)
        await OpsService(self.s).apply_op(
            project_id, "define_custom_field", {"entity": entity, "def": body.model_dump()}, actor
        )
        return await self._get(project_id, entity, body.name)

    async def update(
        self, project_id: uuid.UUID, entity: str, name: str, changes: dict[str, Any], actor: Actor
    ) -> CustomFieldDef:
        await self._get(project_id, entity, name)  # 404s
        await OpsService(self.s).apply_op(
            project_id,
            "update_custom_field",
            {"entity": entity, "name": name, "changes": changes},
            actor,
        )
        return await self._get(project_id, entity, changes.get("name", name))

    async def remove(self, project_id: uuid.UUID, entity: str, name: str, actor: Actor) -> None:
        await self._get(project_id, entity, name)
        await OpsService(self.s).apply_op(
            project_id, "remove_custom_field", {"entity": entity, "name": name}, actor
        )

    async def promote_check(
        self, project_id: uuid.UUID, entity: str, name: str, samples: list[Any] | None
    ) -> PromoteCheckResult:
        spec = await self._spec(project_id)
        _entity(spec, entity)
        problems = check_promotable(spec, entity, name, samples)
        if any(p.code == "custom_field_promote_unavailable" for p in problems):
            raise AppError("not_found", "custom field not found", 404)
        try:
            _, plan = promote(spec, entity, name)
            sql = plan.upgrade_sql()
        except CustomFieldError:
            sql = []
        proven = is_proven(problems, samples)
        warnings = [p.message for p in problems if p.severity == "warning"]
        if not proven and not any(p.severity == "error" for p in problems):
            warnings.append("not proven: the stored values were not (fully) checked against the new column type")
        return PromoteCheckResult(
            ok=not any(p.severity == "error" for p in problems),
            proven=proven,
            warnings=warnings,
            problems=[
                PromoteProblemRead(
                    code=p.code, message=p.message, sample_index=p.sample_index, severity=p.severity
                )
                for p in problems
            ],
            plan_sql=sql,
        )

    async def promote(
        self, project_id: uuid.UUID, entity: str, name: str, actor: Actor
    ) -> PromoteResult:
        before = await self._spec(project_id)
        _entity(before, entity)
        problems = check_promotable(before, entity, name)
        if any(p.code == "custom_field_promote_unavailable" for p in problems):
            raise AppError("not_found", "custom field not found", 404)
        _, plan = promote(before, entity, name)
        applied = await OpsService(self.s).apply_op(
            project_id, "promote_custom_field", {"entity": entity, "name": name}, actor
        )
        after = await self._spec(project_id)
        steps = plan_migration(before, after).steps
        return PromoteResult(
            entity=entity,
            name=name,
            op_seq=applied.op.seq,
            plan_sql=plan.upgrade_sql(),
            migration_steps=[
                MigrationStepRead(
                    kind=s.kind.value, safety=s.safety.value, reason=s.reason, sql_hint=s.sql_hint
                )
                for s in steps
            ],
        )
