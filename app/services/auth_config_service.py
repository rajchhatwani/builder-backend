"""Service layer for project auth configuration.

One ProjectAuthConfig record per project (1:1).  The service exposes get-or-
create semantics: GET on a project that has no auth config yet raises 404;
POST creates; PATCH updates.  DELETE is intentionally absent — auth config
is removed automatically via ON DELETE CASCADE when the project is deleted.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AppError
from app.models.auth_config import ProjectAuthConfig
from app.models.project import Project
from app.schemas.auth_config import AuthConfigCreate, AuthConfigUpdate


def _not_found() -> AppError:
    return AppError(code="not_found", message="auth config not found", status_code=404)


def _already_exists() -> AppError:
    return AppError(
        code="conflict",
        message="auth config already exists for this project; use PATCH to update",
        status_code=409,
    )


class AuthConfigService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_project_or_404(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise AppError(code="not_found", message="project not found", status_code=404)
        return project

    async def _get_config_or_404(self, project_id: uuid.UUID) -> ProjectAuthConfig:
        result = await self.session.execute(
            select(ProjectAuthConfig).where(
                ProjectAuthConfig.project_id == project_id
            )
        )
        config = result.scalar_one_or_none()
        if config is None:
            raise _not_found()
        return config

    # ── Public API ────────────────────────────────────────────────────────────

    async def create(
        self, project_id: uuid.UUID, data: AuthConfigCreate
    ) -> ProjectAuthConfig:
        await self._get_project_or_404(project_id)

        smtp_dict: dict[str, Any] | None = (
            data.smtp_config.model_dump() if data.smtp_config else None
        )
        sms_dict: dict[str, Any] | None = (
            data.sms_config.model_dump() if data.sms_config else None
        )

        config = ProjectAuthConfig(
            project_id=project_id,
            enabled=data.enabled,
            token_store=data.token_store,
            access_token_ttl_minutes=data.access_token_ttl_minutes,
            refresh_token_ttl_days=data.refresh_token_ttl_days,
            jwt_algorithm=data.jwt_algorithm,
            email_magic_link_enabled=data.email_magic_link_enabled,
            sms_otp_enabled=data.sms_otp_enabled,
            otp_ttl_minutes=data.otp_ttl_minutes,
            email_verification_required=data.email_verification_required,
            invite_only=data.invite_only,
            multi_tenant=data.multi_tenant,
            deletion_mode=data.deletion_mode,
            smtp_config=smtp_dict,
            sms_provider=data.sms_provider,
            sms_config=sms_dict,
            login_rate_limit=data.login_rate_limit,
            register_rate_limit=data.register_rate_limit,
            reset_rate_limit=data.reset_rate_limit,
            security_headers_enabled=data.security_headers_enabled,
            app_name=data.app_name,
            app_url=data.app_url,
            email_templates=data.email_templates,
        )
        self.session.add(config)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise _already_exists() from exc
        return config

    async def get(self, project_id: uuid.UUID) -> ProjectAuthConfig:
        await self._get_project_or_404(project_id)
        return await self._get_config_or_404(project_id)

    async def update(
        self, project_id: uuid.UUID, data: AuthConfigUpdate
    ) -> ProjectAuthConfig:
        config = await self.get(project_id)
        updates = data.model_dump(exclude_unset=True)

        # Deserialise nested sub-models that arrive as dicts or BaseModel instances
        if "smtp_config" in updates and updates["smtp_config"] is not None:
            smtp = data.smtp_config
            updates["smtp_config"] = smtp.model_dump() if smtp is not None else None
        if "sms_config" in updates and updates["sms_config"] is not None:
            sms = data.sms_config
            updates["sms_config"] = sms.model_dump() if sms is not None else None

        for key, value in updates.items():
            setattr(config, key, value)

        # Re-validate cross-field invariants on the merged state
        self._assert_invariants(config)

        await self.session.commit()
        return config

    # ── Business rule checks ──────────────────────────────────────────────────

    @staticmethod
    def _assert_invariants(config: ProjectAuthConfig) -> None:
        """Re-check cross-field rules after a partial PATCH."""
        if config.email_magic_link_enabled and config.smtp_config is None:
            raise AppError(
                code="validation_error",
                message="smtp_config is required when email_magic_link_enabled is true",
                status_code=422,
            )
        if config.sms_otp_enabled and (
            config.sms_provider is None or config.sms_config is None
        ):
            raise AppError(
                code="validation_error",
                message=(
                    "sms_provider and sms_config are required when sms_otp_enabled is true"
                ),
                status_code=422,
            )
