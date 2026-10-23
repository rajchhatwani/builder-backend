"""Storage settings of a project, and the guarded switch that turns the feature on or off.

Turning storage off does not drop anything: the settings row is kept, and tables or files a generated
project already created are never removed by regenerating (uploaded files and the audit trail must
survive). The switch needs an explicit confirmation and reports its impact first.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DownloadMode, StorageBackend
from app.core.spec_models import SpecStorage, SpecStorageRoles, SpecStorageSecurity
from app.exceptions import AppError
from app.models.auth_config import ProjectAuthConfig
from app.models.project import Project
from app.models.storage_config import ProjectStorageConfig
from app.schemas.storage import StorageConfigWrite, StorageImpact

_DEPLOYED_NOTE = (
    "Anything already deployed keeps working until you regenerate. The files table, the audit "
    "table and the files in your bucket are never removed by a regenerated build."
)


def _not_found(what: str) -> AppError:
    return AppError(code="not_found", message=f"{what} not found", status_code=404)


def _invalid(message: str) -> AppError:
    return AppError(code="validation_error", message=message, status_code=422)


def config_to_spec(row: ProjectStorageConfig) -> SpecStorage:
    return SpecStorage(
        enabled=row.enabled,
        backend=row.backend.value,
        bucket=row.bucket,
        region=row.region,
        key_prefix=row.key_prefix,
        allowed_types=list(row.allowed_types),
        max_file_mb=row.max_file_mb,
        user_quota_mb=row.user_quota_mb,
        uploads_per_hour=row.uploads_per_hour,
        download_mode=row.download_mode.value,
        allow_inline_images=row.allow_inline_images,
        roles=SpecStorageRoles.model_validate(row.roles),
        security=SpecStorageSecurity.model_validate(row.security),
    )


def apply_spec(row: ProjectStorageConfig, spec: SpecStorage) -> None:
    row.enabled = spec.enabled
    row.backend = StorageBackend(spec.backend)
    row.bucket = spec.bucket
    row.region = spec.region
    row.key_prefix = spec.key_prefix
    row.allowed_types = list(spec.allowed_types)
    row.max_file_mb = spec.max_file_mb
    row.user_quota_mb = spec.user_quota_mb
    row.uploads_per_hour = spec.uploads_per_hour
    row.download_mode = DownloadMode(spec.download_mode)
    row.allow_inline_images = spec.allow_inline_images
    row.roles = spec.roles.model_dump()
    row.security = spec.security.model_dump()


class StorageService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _project(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise _not_found("project")
        return project

    async def _config(self, project_id: uuid.UUID) -> ProjectStorageConfig | None:
        return (
            await self.session.execute(
                select(ProjectStorageConfig).where(ProjectStorageConfig.project_id == project_id)
            )
        ).scalar_one_or_none()

    async def _auth(self, project_id: uuid.UUID) -> ProjectAuthConfig | None:
        return (
            await self.session.execute(
                select(ProjectAuthConfig).where(ProjectAuthConfig.project_id == project_id)
            )
        ).scalar_one_or_none()

    async def get(self, project_id: uuid.UUID) -> ProjectStorageConfig:
        await self._project(project_id)
        config = await self._config(project_id)
        if config is None:
            raise _not_found("storage settings")
        return config

    async def put(self, project_id: uuid.UUID, data: StorageConfigWrite) -> ProjectStorageConfig:
        await self._project(project_id)
        config = await self._config(project_id)
        if config is None:
            config = ProjectStorageConfig(project_id=project_id, enabled=False)
            self.session.add(config)
        enabled = config.enabled  # saving settings never switches the feature
        body = {**data.model_dump(mode="json"), "enabled": enabled}
        apply_spec(config, SpecStorage.model_validate(body))
        await self.session.commit()
        return config

    # --- switching ------------------------------------------------------------------

    async def impact(self, project_id: uuid.UUID, action: str) -> StorageImpact:
        await self._project(project_id)
        config = await self._config(project_id)
        enabled = config is not None and config.enabled
        blockers: list[str] = []
        warnings: list[str] = []

        if action == "enable":
            if enabled:
                blockers.append("File storage is already on for this project.")
            if config is None:
                blockers.append("Save the storage settings first.")
            auth = await self._auth(project_id)
            if auth is None or not auth.enabled:
                blockers.append("File storage needs authentication: turn it on first.")
            warnings.append(
                "The next generated project gets a file API, a files table and an audit table (a "
                "migration), a ClamAV malware scanner container (about 1.5 GB of memory) and "
                "deployment notes. Bucket credentials are never stored here; you set them as "
                "environment variables of the generated project."
            )
        elif action == "disable":
            if not enabled:
                blockers.append("File storage is not on for this project.")
            warnings.append(
                "The file API disappears from the next generated project. Files already in the "
                "bucket stay there and cannot be downloaded or deleted through the API until you "
                "turn storage back on. Entities with file fields stop validating: remove those "
                "fields first."
            )
            warnings.append("Your storage settings are kept, so you can turn storage back on.")
        else:
            raise _invalid("action must be enable or disable")
        warnings.append(_DEPLOYED_NOTE)
        return StorageImpact(
            action=action,
            enabled=enabled,
            can_proceed=not blockers,
            blockers=blockers,
            warnings=warnings,
        )

    async def switch(
        self, project_id: uuid.UUID, action: str, *, confirm: bool
    ) -> ProjectStorageConfig:
        if not confirm:
            raise AppError(
                code="confirmation_required",
                message="switching storage needs confirm=true; read /storage/impact first to "
                "see what it changes",
                status_code=422,
            )
        impact = await self.impact(project_id, action)
        if not impact.can_proceed:
            raise AppError(code="invalid_state", message=" ".join(impact.blockers), status_code=409)
        config = await self.get(project_id)
        config.enabled = action == "enable"
        await self.session.commit()
        return config
