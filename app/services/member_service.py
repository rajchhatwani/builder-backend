import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AppError
from app.models.enums import AccountStatus, MemberRole
from app.models.platform import OrganizationMember, PlatformUser, ProjectMember
from app.models.project import Project
from app.services.platform_auth_service import normalize_email


class MemberService:
    def __init__(self, session: AsyncSession) -> None:
        self.db = session

    async def list(self, project_id: uuid.UUID) -> list[tuple[ProjectMember, PlatformUser]]:
        rows = await self.db.execute(
            select(ProjectMember, PlatformUser)
            .join(PlatformUser, PlatformUser.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project_id)
            .order_by(ProjectMember.created_at, PlatformUser.email)
        )
        return [(m, u) for m, u in rows.all()]

    async def add(
        self, project_id: uuid.UUID, email: str, role: MemberRole, mcp_enabled: bool = False
    ) -> tuple[ProjectMember, PlatformUser]:
        query = select(PlatformUser).where(PlatformUser.email == normalize_email(email))
        # §3.2: a project member must belong to the project's organization first. Sharing
        # outside it means inviting them to the org (which is where seats are counted).
        project = await self.db.get(Project, project_id)
        if project is not None and project.organization_id is not None:
            query = query.join(
                OrganizationMember,
                (OrganizationMember.user_id == PlatformUser.id)
                & (OrganizationMember.organization_id == project.organization_id),
            )
        user = (await self.db.execute(query)).scalar_one_or_none()
        # One answer for "no such person", "suspended" and "not in this org": do not confirm
        # which addresses exist on the platform.
        if user is None or user.status is not AccountStatus.active:
            raise AppError(
                code="user_unavailable",
                message="no active account with that e-mail in this organization",
                status_code=404,
            )
        existing = await self.db.get(ProjectMember, (project_id, user.id))
        if existing is not None:
            raise AppError(code="conflict", message="already a member", status_code=409)
        member = ProjectMember(
            project_id=project_id,
            user_id=user.id,
            role=role,
            mcp_enabled=mcp_enabled,
        )
        self.db.add(member)
        await self.db.commit()
        return member, user

    async def set_role(
        self, project_id: uuid.UUID, user_id: uuid.UUID, role: MemberRole
    ) -> tuple[ProjectMember, PlatformUser]:
        member = await self._get(project_id, user_id)
        if member.role is MemberRole.owner and role is not MemberRole.owner:
            await self._require_another_owner(project_id, user_id)
        member.role = role
        await self.db.commit()
        user = await self.db.get(PlatformUser, user_id)
        assert user is not None
        return member, user

    async def set_mcp_enabled(
        self, project_id: uuid.UUID, user_id: uuid.UUID, mcp_enabled: bool
    ) -> tuple[ProjectMember, PlatformUser]:
        member = await self._get(project_id, user_id)
        member.mcp_enabled = mcp_enabled
        await self.db.commit()
        user = await self.db.get(PlatformUser, user_id)
        assert user is not None
        return member, user

    async def remove(self, project_id: uuid.UUID, user_id: uuid.UUID) -> None:
        member = await self._get(project_id, user_id)
        if member.role is MemberRole.owner:
            await self._require_another_owner(project_id, user_id)
        await self.db.delete(member)
        await self.db.commit()

    async def _get(self, project_id: uuid.UUID, user_id: uuid.UUID) -> ProjectMember:
        member = await self.db.get(ProjectMember, (project_id, user_id))
        if member is None:
            raise AppError(code="not_found", message="member not found", status_code=404)
        return member

    async def _require_another_owner(self, project_id: uuid.UUID, user_id: uuid.UUID) -> None:
        # Lock the owner rows so two owners removing each other serialise: the second one
        # re-evaluates the role filter after the first commits and sees no other owner.
        others = len(
            (
                await self.db.execute(
                    select(ProjectMember.user_id)
                    .where(
                        ProjectMember.project_id == project_id,
                        ProjectMember.role == MemberRole.owner,
                        ProjectMember.user_id != user_id,
                    )
                    .with_for_update()
                )
            ).all()
        )
        if not others:
            raise AppError(
                code="last_owner",
                message="a project needs at least one owner; make someone else an owner first",
                status_code=409,
            )
