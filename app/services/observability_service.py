"""Observability (OpenTelemetry) settings of a project."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import observability as obs
from app.core.spec_models import SpecObservability
from app.exceptions import AppError
from app.models.observability_config import ProjectObservability
from app.models.project import Project
from app.schemas.observability import ObservabilityRead, ObservabilityWrite


def config_to_spec(row: ProjectObservability) -> SpecObservability:
    return SpecObservability.model_validate({**row.settings, "enabled": row.enabled})


def apply_spec(row: ProjectObservability, spec: SpecObservability) -> None:
    row.enabled = spec.enabled
    row.settings = spec.model_dump(mode="json", exclude={"enabled"})


class ObservabilityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _project(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise AppError(code="not_found", message="project not found", status_code=404)
        return project

    async def _row(self, project_id: uuid.UUID) -> ProjectObservability | None:
        return (
            await self.session.execute(
                select(ProjectObservability).where(ProjectObservability.project_id == project_id)
            )
        ).scalar_one_or_none()

    def _read(
        self,
        project: Project,
        spec: SpecObservability,
        version: int,
        row: ProjectObservability | None,
    ) -> ObservabilityRead:
        return ObservabilityRead(
            **spec.model_dump(),
            project_id=project.id,
            version=version,
            updated_at=row.updated_at if row is not None else None,
            recommended_sample_ratio=obs.recommended_sample_ratio(spec.expected_rps),
            default_service_name=project.slug,
            redacted_keys=list(obs.BUILTIN_REDACT_KEYS),
        )

    async def get(self, project_id: uuid.UUID) -> ObservabilityRead:
        project = await self._project(project_id)
        row = await self._row(project_id)
        if row is None:
            # Never saved: nothing is generated until the settings are saved (and enabled).
            return self._read(project, SpecObservability(enabled=False), 0, None)
        return self._read(project, config_to_spec(row), row.version, row)

    async def put(self, project_id: uuid.UUID, data: ObservabilityWrite) -> ObservabilityRead:
        await self._project(project_id)
        row = await self._row(project_id)
        current = row.version if row is not None else 0
        if data.expected_version is not None and data.expected_version != current:
            raise AppError(
                code="conflict",
                message="the observability settings changed since you opened them; reload and "
                "apply your edit again",
                status_code=409,
            )
        spec = SpecObservability.model_validate(data.model_dump(exclude={"expected_version"}))
        if row is None:
            row = ProjectObservability(project_id=project_id, version=1)
            self.session.add(row)
        else:
            row.version = current + 1
        apply_spec(row, spec)
        await self.session.commit()
        return await self.get(project_id)
