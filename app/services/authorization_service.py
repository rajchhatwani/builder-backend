"""Authorization settings of a project: the model (rbac / abac / pbac) and its policies.

Saving never validates the policies against the entities (work in progress is allowed); the
issues endpoint and `/validate` report every problem, and generation refuses an invalid spec.
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import authz_engine as eng
from app.core import authz_recommender as recommender
from app.core import authz_tools
from app.core.enums import AuthorizationModel
from app.core.spec_models import Spec, SpecAuthorization, SpecPolicy
from app.exceptions import AppError
from app.models.authorization_config import ProjectAuthorization
from app.models.project import Project
from app.schemas.authorization import (
    AuthorizationRead,
    AuthorizationWrite,
    CoverageResponse,
    PolicyBody,
    RecommendRequest,
    RecommendResponse,
    SimulateRequest,
    SimulateResponse,
)

if TYPE_CHECKING:
    from app.services.spec_service import SpecService


def config_to_spec(row: ProjectAuthorization) -> SpecAuthorization:
    return SpecAuthorization(
        model=row.model,
        policies=[SpecPolicy.model_validate(p) for p in row.policies],
        attachments={k: list(v) for k, v in row.attachments.items()},
    )


def apply_spec(row: ProjectAuthorization, spec: SpecAuthorization) -> None:
    row.model = spec.model
    row.policies = [p.model_dump(mode="json") for p in spec.policies]
    row.attachments = {k: list(v) for k, v in spec.attachments.items()}


def recommend(answers: RecommendRequest) -> RecommendResponse:
    result = recommender.recommend(recommender.Answers(**answers.model_dump()))
    return RecommendResponse.model_validate(result)


def _spec_service(session: AsyncSession) -> "SpecService":
    # Imported late: spec_service imports this module for the spec <-> row mapping.
    from app.services.spec_service import SpecService

    return SpecService(session)


def _invalid(message: str) -> AppError:
    return AppError(code="validation_error", message=message, status_code=422)


class AuthorizationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _project(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise AppError(code="not_found", message="project not found", status_code=404)
        return project

    async def _row(self, project_id: uuid.UUID) -> ProjectAuthorization | None:
        return (
            await self.session.execute(
                select(ProjectAuthorization).where(ProjectAuthorization.project_id == project_id)
            )
        ).scalar_one_or_none()

    async def get(self, project_id: uuid.UUID) -> AuthorizationRead:
        await self._project(project_id)
        row = await self._row(project_id)
        if row is None:
            return AuthorizationRead(
                project_id=project_id,
                model=AuthorizationModel.rbac,
                policies=[],
                attachments={},
                version=0,
            )
        return AuthorizationRead(
            project_id=project_id,
            model=AuthorizationModel(row.model),
            policies=[PolicyBody.model_validate(p) for p in row.policies],
            attachments=row.attachments,
            version=row.version,
            updated_at=row.updated_at,
        )

    async def put(self, project_id: uuid.UUID, data: AuthorizationWrite) -> AuthorizationRead:
        await self._project(project_id)
        row = await self._row(project_id)
        current = row.version if row is not None else 0
        if data.expected_version is not None and data.expected_version != current:
            raise AppError(
                code="conflict",
                message="the authorization settings changed since you opened them; reload and "
                "apply your edit again",
                status_code=409,
            )
        ids = [p.id for p in data.policies]
        if len(ids) != len(set(ids)):
            raise _invalid("policy ids must be unique")
        spec = SpecAuthorization(
            model=data.model.value,
            policies=[SpecPolicy.model_validate(p.model_dump()) for p in data.policies],
            attachments=data.attachments,
        )
        if row is None:
            row = ProjectAuthorization(project_id=project_id, version=1)
            self.session.add(row)
        else:
            row.version = current + 1
        apply_spec(row, spec)
        await self.session.commit()
        return await self.get(project_id)

    async def issues(self, project_id: uuid.UUID) -> list[dict[str, str]]:
        await self._project(project_id)
        found = await _spec_service(self.session).validate(project_id)
        return [
            i.model_dump()
            for i in found
            if i.path.startswith("authorization")
            or i.code.startswith("authz.")
            or i.path.startswith("auth.permissions")
        ]

    async def _active_spec(self, project_id: uuid.UUID) -> Spec:
        await self._project(project_id)
        spec = await _spec_service(self.session).assemble(project_id)
        if spec.authorization is None or spec.authorization.model == AuthorizationModel.rbac:
            raise AppError(
                code="invalid_state",
                message="the simulator and the coverage matrix need the abac or pbac model: "
                "save it first",
                status_code=409,
            )
        return spec

    async def simulate(self, project_id: uuid.UUID, body: SimulateRequest) -> SimulateResponse:
        spec = await self._active_spec(project_id)
        if all(e.name != body.entity for e in spec.entities):
            raise _invalid(f"no entity named {body.entity}")
        if body.op not in eng.OPERATIONS:
            raise _invalid(f"op must be one of {', '.join(eng.OPERATIONS)}")
        subject = dict(body.subject)
        roles = subject.get("roles") or []
        if not isinstance(roles, list) or not all(isinstance(r, str) for r in roles):
            raise _invalid("subject.roles must be a list of role names")
        try:
            result = authz_tools.simulate(
                spec,
                entity=body.entity,
                op=body.op,
                subject=subject,
                resource=body.resource,
                env=body.env,
            )
        except eng.PolicyError as exc:
            raise _invalid(f"the policies are not valid yet: {exc}") from exc
        return SimulateResponse.model_validate(result)

    async def coverage(self, project_id: uuid.UUID) -> CoverageResponse:
        spec = await self._active_spec(project_id)
        try:
            rows = authz_tools.coverage(spec)
        except eng.PolicyError as exc:
            raise _invalid(f"the policies are not valid yet: {exc}") from exc
        assert spec.authorization is not None
        return CoverageResponse(model=AuthorizationModel(spec.authorization.model), rows=rows)

    async def recommend_for_project(self, project_id: uuid.UUID) -> RecommendResponse:
        await self._project(project_id)
        spec = await _spec_service(self.session).assemble(project_id)
        result = recommender.recommend(recommender.answers_from_spec(spec))
        return RecommendResponse.model_validate(result)
