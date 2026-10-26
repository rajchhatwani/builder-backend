import uuid

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.naming import slugify
from app.exceptions import AppError
from app.models.enums import MemberRole
from app.models.platform import PlatformUser, ProjectMember
from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectUpdate


def _slug_conflict() -> AppError:
    return AppError(
        code="conflict", message="a project with this slug already exists", status_code=409
    )


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, data: ProjectCreate, owner: PlatformUser, *, organization_id: uuid.UUID | None = None
    ) -> Project:
        """Create a project owned by `owner` inside `organization_id` (defaults to the owner's
        default org). Enforces the plan's project cap transactionally."""
        from app.services.organization_service import OrganizationService

        org_service = OrganizationService(self.session)
        if organization_id is None:
            # Fall back to default org; create a personal one if the user has none yet (older
            # accounts predating Phase A).
            organization_id = owner.default_organization_id
            if organization_id is None:
                org = await org_service.ensure_personal_org(owner)
                organization_id = org.id
                await self.session.flush()
        role = await org_service.member_role(owner.id, organization_id)
        if role is None:
            raise AppError(
                code="forbidden",
                message="you must be a member of this organization to create a project",
                status_code=403,
            )
        # §6.2: locks the subscription row until the commit below, so concurrent creates
        # in one org cannot overshoot the cap.
        await org_service.enforce_project_limit(
            organization_id, actor_id=owner.id, actor_email=owner.email
        )

        project = Project(
            name=data.name,
            slug=data.slug or slugify(data.name),
            description=data.description,
            db_engine=data.db_engine,
            organization_id=organization_id,
        )
        self.session.add(project)
        try:
            await self.session.flush()
            # The creator owns the project from its first moment; there is never an ownerless one.
            self.session.add(
                ProjectMember(project_id=project.id, user_id=owner.id, role=MemberRole.owner)
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise _slug_conflict() from exc
        return project

    async def list(
        self, user_id: uuid.UUID, limit: int, offset: int, only_project: uuid.UUID | None = None
    ) -> tuple[list[Project], int]:
        """Only the projects `user_id` is a member of (an API token may be pinned to just one)."""
        member_of = select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)
        conditions: list[ColumnElement[bool]] = [Project.id.in_(member_of)]
        if only_project is not None:
            conditions.append(Project.id == only_project)
        total = (
            await self.session.execute(select(func.count()).select_from(Project).where(*conditions))
        ).scalar_one()
        rows = (
            await self.session.execute(
                select(Project)
                .where(*conditions)
                .order_by(Project.created_at)
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
        return list(rows), total

    async def get(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise AppError(code="not_found", message="project not found", status_code=404)
        return project

    async def update(self, project_id: uuid.UUID, data: ProjectUpdate) -> Project:
        project = await self.get(project_id)
        if project.version != data.version:
            raise AppError(
                code="conflict",
                message="project was modified by someone else; refetch and retry",
                status_code=409,
            )
        updates = data.model_dump(exclude_unset=True, exclude={"version"})
        for key, value in updates.items():
            setattr(project, key, value)
        project.version += 1
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise _slug_conflict() from exc
        return project

    async def delete(self, project_id: uuid.UUID) -> None:
        project = await self.get(project_id)
        await self.session.delete(project)
        await self.session.commit()
