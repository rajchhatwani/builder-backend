import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.naming import slugify
from app.exceptions import AppError
from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectUpdate


def _slug_conflict() -> AppError:
    return AppError(
        code="conflict", message="a project with this slug already exists", status_code=409
    )


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, data: ProjectCreate) -> Project:
        project = Project(
            name=data.name,
            slug=data.slug or slugify(data.name),
            description=data.description,
            db_engine=data.db_engine,
        )
        self.session.add(project)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise _slug_conflict() from exc
        return project

    async def list(self, limit: int, offset: int) -> tuple[list[Project], int]:
        total = (await self.session.execute(select(func.count()).select_from(Project))).scalar_one()
        rows = (
            await self.session.execute(
                select(Project).order_by(Project.created_at).limit(limit).offset(offset)
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
