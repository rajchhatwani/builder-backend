"""Cloud deployment settings of a project, and the preview of what they generate."""

import uuid
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import deploy_sizing as sizing
from app.core.generator.features.deploy.module import tfvars_for
from app.core.spec_models import SpecDeployEnvironment, SpecDeployment
from app.exceptions import AppError
from app.models.deployment_config import ProjectDeployment
from app.models.project import Project
from app.schemas.deployment import (
    DeploymentPlan,
    DeploymentRead,
    DeploymentWrite,
    ResolvedEnvironment,
)

_NOTES = {
    "aws": [
        "ECS Fargate behind an Application Load Balancer, RDS PostgreSQL in private subnets, "
        "secrets in Secrets Manager. A TLS certificate (ACM) is required outside dev.",
        "A NAT gateway is billed by the hour: it is the largest fixed cost of a small environment.",
    ],
    "azure": [
        "Container Apps with managed HTTPS, PostgreSQL Flexible Server on a private network, "
        "secrets in Key Vault.",
    ],
    "gcp": [
        "Cloud Run with managed HTTPS, Cloud SQL with a private IP, secrets in Secret Manager. "
        "There is no WAF in front of Cloud Run in this bundle.",
    ],
}


def config_to_spec(row: ProjectDeployment) -> SpecDeployment:
    return SpecDeployment.model_validate(
        {
            "enabled": row.enabled,
            "cloud": row.cloud,
            "region": row.region,
            "github_repo": row.github_repo,
            "environments": row.environments,
        }
    )


def apply_spec(row: ProjectDeployment, spec: SpecDeployment) -> None:
    row.enabled = spec.enabled
    row.cloud = spec.cloud
    row.region = spec.region
    row.github_repo = spec.github_repo
    row.environments = [e.model_dump(mode="json") for e in spec.environments]


def plan_for(spec: SpecDeployment) -> DeploymentPlan:
    """Concrete numbers for every environment that is valid enough to resolve."""
    resolved: list[ResolvedEnvironment] = []
    if spec.cloud in sizing.CLOUDS:
        for env in spec.environments:
            if env.profile not in sizing.PROFILES:
                continue
            fields = env.model_dump(exclude={"name", "profile"})
            r = sizing.resolve(spec.cloud, env.name, env.profile, **fields)
            resolved.append(ResolvedEnvironment(**asdict(r), tfvars=tfvars_for(spec, r)))
    return DeploymentPlan(
        cloud=spec.cloud,
        region=spec.region,
        environments=resolved,
        valid_sizes=sizing.combos(spec.cloud),
        notes=_NOTES.get(spec.cloud, []),
    )


def _default_environments() -> list[SpecDeployEnvironment]:
    return SpecDeployment().environments


class DeploymentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _project(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise AppError(code="not_found", message="project not found", status_code=404)
        return project

    async def _row(self, project_id: uuid.UUID) -> ProjectDeployment | None:
        return (
            await self.session.execute(
                select(ProjectDeployment).where(ProjectDeployment.project_id == project_id)
            )
        ).scalar_one_or_none()

    def _read(self, project_id: uuid.UUID, row: ProjectDeployment | None) -> DeploymentRead:
        if row is None:
            spec = SpecDeployment(enabled=False)
            return DeploymentRead(project_id=project_id, version=0, **spec.model_dump(mode="json"))
        spec = config_to_spec(row)
        return DeploymentRead(
            project_id=project_id,
            version=row.version,
            updated_at=row.updated_at,
            **spec.model_dump(mode="json"),
        )

    async def get(self, project_id: uuid.UUID) -> DeploymentRead:
        await self._project(project_id)
        return self._read(project_id, await self._row(project_id))

    async def put(self, project_id: uuid.UUID, data: DeploymentWrite) -> DeploymentRead:
        await self._project(project_id)
        row = await self._row(project_id)
        current = row.version if row is not None else 0
        if data.expected_version is not None and data.expected_version != current:
            raise AppError(
                code="conflict",
                message="the deployment settings changed since you opened them; reload and apply "
                "your edit again",
                status_code=409,
            )
        spec = SpecDeployment.model_validate(data.model_dump(exclude={"expected_version"}))
        if row is None:
            row = ProjectDeployment(project_id=project_id, version=1)
            self.session.add(row)
        else:
            row.version = current + 1
        apply_spec(row, spec)
        await self.session.commit()
        return await self.get(project_id)

    @staticmethod
    def preview(body: DeploymentWrite) -> DeploymentPlan:
        """A plan for settings that are not saved (the dashboard form, live)."""
        spec = SpecDeployment.model_validate(body.model_dump(exclude={"expected_version"}))
        return plan_for(spec)
