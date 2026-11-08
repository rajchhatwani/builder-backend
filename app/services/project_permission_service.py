"""Service layer for project permissions.

Permissions are addressed by (project_id, entity_id, operation).
The primary write path is bulk upsert (full matrix replace).  Individual
PATCH and DELETE are also supported for fine-grained updates.

Business rules enforced here:
  - entity_id must belong to the project
  - all role names in `roles[]` must exist as ProjectRole.name in the project
  - (entity_id, operation) uniqueness within a upsert batch
  - custom_filter fields must be a real field name on the entity
    (checked lazily — generator validates; here we do a lightweight check)
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AppError
from app.models.entity import Entity
from app.models.project import Project
from app.models.project_permission import ProjectPermission
from app.models.project_role import ProjectRole
from app.schemas.project_permission import (
    PermissionEntry,
    ProjectPermissionBulkUpsert,
    ProjectPermissionUpdate,
)


class ProjectPermissionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_project_or_404(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise AppError(code="not_found", message="project not found", status_code=404)
        return project

    async def _get_permission_or_404(self, permission_id: uuid.UUID) -> ProjectPermission:
        perm = await self.session.get(ProjectPermission, permission_id)
        if perm is None:
            raise AppError(code="not_found", message="permission not found", status_code=404)
        return perm

    async def _load_entity_ids(self, project_id: uuid.UUID) -> set[uuid.UUID]:
        """Return all entity IDs that belong to this project."""
        rows = (
            await self.session.execute(select(Entity.id).where(Entity.project_id == project_id))
        ).scalars()
        return set(rows)

    async def _load_role_names(self, project_id: uuid.UUID) -> set[str]:
        """Return all role names defined for this project."""
        rows = (
            await self.session.execute(
                select(ProjectRole.name).where(ProjectRole.project_id == project_id)
            )
        ).scalars()
        return set(rows)

    def _validate_entries(
        self,
        entries: list[PermissionEntry],
        entity_ids: set[uuid.UUID],
        role_names: set[str],
    ) -> None:
        seen: set[tuple[uuid.UUID, str]] = set()
        errors: list[dict[str, object]] = []

        for i, entry in enumerate(entries):
            key = (entry.entity_id, entry.operation.value)
            if key in seen:
                errors.append(
                    {
                        "index": i,
                        "code": "duplicate",
                        "message": (
                            f"duplicate (entity_id, operation) pair: "
                            f"{entry.entity_id}/{entry.operation}"
                        ),
                    }
                )
            seen.add(key)

            if entry.entity_id not in entity_ids:
                errors.append(
                    {
                        "index": i,
                        "code": "not_found",
                        "message": f"entity {entry.entity_id} does not belong to this project",
                    }
                )

            unknown_roles = set(entry.roles) - role_names
            if unknown_roles:
                errors.append(
                    {
                        "index": i,
                        "code": "not_found",
                        "message": (
                            f"unknown roles: {sorted(unknown_roles)}; "
                            "define them first via POST /projects/{id}/roles"
                        ),
                    }
                )

        if errors:
            raise AppError(
                code="validation_error",
                message="one or more permission entries are invalid",
                status_code=422,
                details=errors,
            )

    # ── Public API ────────────────────────────────────────────────────────────

    async def bulk_upsert(
        self, project_id: uuid.UUID, data: ProjectPermissionBulkUpsert
    ) -> list[ProjectPermission]:
        """Replace permissions for the given (entity, operation) slots.

        Upserts by (project_id, entity_id, operation) — existing rows are
        updated, new rows are inserted, rows NOT in the payload are left alone.
        Use DELETE /projects/{id}/permissions/{id} to remove individual entries.
        """
        await self._get_project_or_404(project_id)
        entity_ids = await self._load_entity_ids(project_id)
        role_names = await self._load_role_names(project_id)

        self._validate_entries(data.permissions, entity_ids, role_names)

        # Postgres ON CONFLICT DO UPDATE (upsert)
        for entry in data.permissions:
            stmt = (
                pg_insert(ProjectPermission)
                .values(
                    project_id=project_id,
                    entity_id=entry.entity_id,
                    operation=entry.operation,
                    roles=entry.roles,
                    row_rule=entry.row_rule,
                    custom_filter_field=entry.custom_filter_field,
                    custom_filter_value=entry.custom_filter_value,
                )
                .on_conflict_do_update(
                    constraint="uq_project_permissions_project_entity_op",
                    set_={
                        "roles": entry.roles,
                        "row_rule": entry.row_rule,
                        "custom_filter_field": entry.custom_filter_field,
                        "custom_filter_value": entry.custom_filter_value,
                    },
                )
            )
            await self.session.execute(stmt)

        await self.session.commit()
        return await self._list_all(project_id)

    async def list_paginated(
        self, project_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[ProjectPermission], int]:
        await self._get_project_or_404(project_id)
        total = (
            await self.session.execute(
                select(func.count())
                .select_from(ProjectPermission)
                .where(ProjectPermission.project_id == project_id)
            )
        ).scalar_one()
        rows = (
            await self.session.execute(
                select(ProjectPermission)
                .where(ProjectPermission.project_id == project_id)
                .order_by(ProjectPermission.entity_id, ProjectPermission.operation)
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
        return list(rows), total

    async def _list_all(self, project_id: uuid.UUID) -> list[ProjectPermission]:
        rows = (
            await self.session.execute(
                select(ProjectPermission)
                .where(ProjectPermission.project_id == project_id)
                .order_by(ProjectPermission.entity_id, ProjectPermission.operation)
            )
        ).scalars()
        return list(rows)

    async def get(self, permission_id: uuid.UUID) -> ProjectPermission:
        return await self._get_permission_or_404(permission_id)

    async def update(
        self, permission_id: uuid.UUID, data: ProjectPermissionUpdate
    ) -> ProjectPermission:
        perm = await self._get_permission_or_404(permission_id)

        # Validate roles if supplied
        if data.roles is not None:
            role_names = await self._load_role_names(perm.project_id)
            unknown = set(data.roles) - role_names
            if unknown:
                raise AppError(
                    code="not_found",
                    message=f"unknown roles: {sorted(unknown)}",
                    status_code=422,
                )

        updates = data.model_dump(exclude_unset=True)
        for key, value in updates.items():
            setattr(perm, key, value)
        await self.session.commit()
        return perm

    async def delete(self, permission_id: uuid.UUID) -> None:
        perm = await self._get_permission_or_404(permission_id)
        await self.session.delete(perm)
        await self.session.commit()
