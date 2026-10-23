"""Service layer for project roles.

Business rules enforced here (not in the DB):
  - At most one role per project may have is_default=True.
  - Role names follow snake_case identifier rules.
  - `inherits_from` must reference an existing role in the same project.
  - A role cannot inherit from itself (direct or indirect cycles caught).
  - The default role cannot be deleted; it must be reassigned first.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AppError
from app.models.project import Project
from app.models.project_role import ProjectRole
from app.schemas.project_role import ProjectRoleCreate, ProjectRoleUpdate


def _name_conflict() -> AppError:
    return AppError(
        code="conflict",
        message="a role with this name already exists in this project",
        status_code=409,
    )


class ProjectRoleService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_project_or_404(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise AppError(code="not_found", message="project not found", status_code=404)
        return project

    async def _get_role_or_404(self, role_id: uuid.UUID) -> ProjectRole:
        role = await self.session.get(ProjectRole, role_id)
        if role is None:
            raise AppError(code="not_found", message="role not found", status_code=404)
        return role

    async def _get_role_by_name(
        self, project_id: uuid.UUID, name: str
    ) -> ProjectRole | None:
        result = await self.session.execute(
            select(ProjectRole).where(
                ProjectRole.project_id == project_id,
                ProjectRole.name == name,
            )
        )
        return result.scalar_one_or_none()

    async def _count_defaults(self, project_id: uuid.UUID) -> int:
        return (
            await self.session.execute(
                select(func.count()).select_from(ProjectRole).where(
                    ProjectRole.project_id == project_id,
                    ProjectRole.is_default.is_(True),
                )
            )
        ).scalar_one()

    async def _assert_inherits_exists(
        self, project_id: uuid.UUID, inherits_from: str | None
    ) -> None:
        if inherits_from is None:
            return
        existing = await self._get_role_by_name(project_id, inherits_from)
        if existing is None:
            raise AppError(
                code="not_found",
                message=f"role '{inherits_from}' not found in this project",
                status_code=422,
            )

    async def _assert_no_cycle(self, project_id: uuid.UUID, name: str, parent: str) -> None:
        """Walk up from `parent`; reaching `name` again means the chain loops."""
        seen = {name}
        cursor: str | None = parent
        while cursor is not None:
            if cursor in seen:
                raise AppError(
                    code="validation_error",
                    message="role inheritance must not form a cycle",
                    status_code=422,
                )
            seen.add(cursor)
            ancestor = await self._get_role_by_name(project_id, cursor)
            cursor = ancestor.inherits_from if ancestor is not None else None

    # ── Public API ────────────────────────────────────────────────────────────

    async def create(self, project_id: uuid.UUID, data: ProjectRoleCreate) -> ProjectRole:
        await self._get_project_or_404(project_id)
        await self._assert_inherits_exists(project_id, data.inherits_from)

        if data.inherits_from == data.name:
            raise AppError(
                code="validation_error",
                message="a role cannot inherit from itself",
                status_code=422,
            )

        if data.is_default:
            current_defaults = await self._count_defaults(project_id)
            if current_defaults > 0:
                raise AppError(
                    code="conflict",
                    message=(
                        "another role is already marked as default; "
                        "update that role first (set is_default=false)"
                    ),
                    status_code=409,
                )

        role = ProjectRole(
            project_id=project_id,
            name=data.name,
            label=data.label,
            is_default=data.is_default,
            self_assignable=data.self_assignable,
            invite_only=data.invite_only,
            inherits_from=data.inherits_from,
            position=data.position,
        )
        self.session.add(role)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise _name_conflict() from exc
        return role

    async def list(
        self, project_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[ProjectRole], int]:
        await self._get_project_or_404(project_id)
        total = (
            await self.session.execute(
                select(func.count()).select_from(ProjectRole).where(
                    ProjectRole.project_id == project_id
                )
            )
        ).scalar_one()
        rows = (
            await self.session.execute(
                select(ProjectRole)
                .where(ProjectRole.project_id == project_id)
                .order_by(ProjectRole.position, ProjectRole.name)
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
        return list(rows), total

    async def get(self, role_id: uuid.UUID) -> ProjectRole:
        return await self._get_role_or_404(role_id)

    async def update(self, role_id: uuid.UUID, data: ProjectRoleUpdate) -> ProjectRole:
        role = await self._get_role_or_404(role_id)
        updates = data.model_dump(exclude_unset=True)

        # Guard: if setting is_default=True, ensure no other default exists
        if updates.get("is_default") is True and not role.is_default:
            current_defaults = await self._count_defaults(role.project_id)
            if current_defaults > 0:
                raise AppError(
                    code="conflict",
                    message=(
                        "another role is already marked as default; "
                        "update that role first (set is_default=false)"
                    ),
                    status_code=409,
                )

        # Guard: inherits_from must exist in same project
        if "inherits_from" in updates and updates["inherits_from"] is not None:
            await self._assert_inherits_exists(role.project_id, updates["inherits_from"])
            if updates["inherits_from"] == role.name:
                raise AppError(
                    code="validation_error",
                    message="a role cannot inherit from itself",
                    status_code=422,
                )
            await self._assert_no_cycle(role.project_id, role.name, updates["inherits_from"])

        for key, value in updates.items():
            setattr(role, key, value)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise _name_conflict() from exc
        return role

    async def delete(self, role_id: uuid.UUID) -> None:
        role = await self._get_role_or_404(role_id)
        if role.is_default:
            raise AppError(
                code="conflict",
                message=(
                    "cannot delete the default role; "
                    "assign another role as default first"
                ),
                status_code=409,
            )
        # Guard: no other role inherits from this one (would leave a dangling ref)
        inheritors = (
            await self.session.execute(
                select(func.count()).select_from(ProjectRole).where(
                    ProjectRole.project_id == role.project_id,
                    ProjectRole.inherits_from == role.name,
                )
            )
        ).scalar_one()
        if inheritors > 0:
            raise AppError(
                code="conflict",
                message=(
                    f"cannot delete role '{role.name}' because other roles inherit from it; "
                    "update those roles first"
                ),
                status_code=409,
            )
        await self.session.delete(role)
        await self.session.commit()
