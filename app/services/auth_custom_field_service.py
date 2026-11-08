"""Service layer for auth custom registration fields.

Business rules:
  - Field names are unique per project (DB unique constraint + friendly error).
  - Names must not clash with RESERVED_USER_FIELD_NAMES.
  - Type/constraint coherence is validated in the schema layer; the service
    enforces the reserved-name check which requires DB access.
  - Position is auto-assigned (max+1) if not provided.
  - Type cannot be changed after creation (changing a column type in Postgres
    requires a migration; the dashboard should delete and re-add the field).
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AppError
from app.models.auth_custom_field import RESERVED_USER_FIELD_NAMES, AuthCustomField
from app.models.project import Project
from app.schemas.auth_custom_field import AuthCustomFieldCreate, AuthCustomFieldUpdate


def _name_conflict() -> AppError:
    return AppError(
        code="conflict",
        message="a custom field with this name already exists for this project",
        status_code=409,
    )


class AuthCustomFieldService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_project_or_404(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise AppError(code="not_found", message="project not found", status_code=404)
        return project

    async def _get_field_or_404(self, field_id: uuid.UUID) -> AuthCustomField:
        field = await self.session.get(AuthCustomField, field_id)
        if field is None:
            raise AppError(code="not_found", message="custom field not found", status_code=404)
        return field

    def _assert_not_reserved(self, name: str) -> None:
        if name in RESERVED_USER_FIELD_NAMES:
            raise AppError(
                code="conflict",
                message=(
                    f"'{name}' is a reserved field name in the generated user model "
                    f"and cannot be used as a custom field name"
                ),
                status_code=409,
            )

    # ── Public API ────────────────────────────────────────────────────────────

    async def create(self, project_id: uuid.UUID, data: AuthCustomFieldCreate) -> AuthCustomField:
        await self._get_project_or_404(project_id)
        self._assert_not_reserved(data.name)

        position = data.position
        if position == 0:
            # Auto-assign as last position when caller didn't specify
            max_pos = (
                await self.session.execute(
                    select(func.max(AuthCustomField.position)).where(
                        AuthCustomField.project_id == project_id
                    )
                )
            ).scalar_one_or_none()
            if max_pos is not None:
                position = max_pos + 1

        field = AuthCustomField(
            project_id=project_id,
            name=data.name,
            label=data.label,
            type=data.type,
            required=data.required,
            unique=data.unique,
            indexed=data.indexed,
            min_length=data.min_length,
            max_length=data.max_length,
            min_value=data.min_value,
            max_value=data.max_value,
            default_value=data.default_value,
            enum_values=data.enum_values,
            extra=data.extra,
            position=position,
        )
        self.session.add(field)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise _name_conflict() from exc
        return field

    async def list(
        self, project_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[AuthCustomField], int]:
        await self._get_project_or_404(project_id)
        total = (
            await self.session.execute(
                select(func.count())
                .select_from(AuthCustomField)
                .where(AuthCustomField.project_id == project_id)
            )
        ).scalar_one()
        rows = (
            await self.session.execute(
                select(AuthCustomField)
                .where(AuthCustomField.project_id == project_id)
                .order_by(AuthCustomField.position, AuthCustomField.name)
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
        return list(rows), total

    async def get(self, field_id: uuid.UUID) -> AuthCustomField:
        return await self._get_field_or_404(field_id)

    async def update(self, field_id: uuid.UUID, data: AuthCustomFieldUpdate) -> AuthCustomField:
        field = await self._get_field_or_404(field_id)
        updates = data.model_dump(exclude_unset=True)
        # type cannot be changed (would require a migration)
        if "type" in updates:
            raise AppError(
                code="validation_error",
                message=(
                    "field type cannot be changed after creation; "
                    "delete and re-create the field instead"
                ),
                status_code=422,
            )
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
