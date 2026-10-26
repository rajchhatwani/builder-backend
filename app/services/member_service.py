import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AppError
from app.models.enums import AccountStatus, MemberRole
from app.models.platform import PlatformUser, ProjectMember
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
        user = (
            await self.db.execute(
                select(PlatformUser).where(PlatformUser.email == normalize_email(email))
            )
        ).scalar_one_or_none()
        # One answer for "no such person" and "suspended": do not confirm which addresses exist.
        if user is None or user.status is not AccountStatus.active:
            raise AppError(
                code="user_unavailable",
                message="no active account with that e-mail",
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
        others = (
            await self.db.execute(
                select(func.count())
                .select_from(ProjectMember)
                .where(
                    ProjectMember.project_id == project_id,
                    ProjectMember.role == MemberRole.owner,
                    ProjectMember.user_id != user_id,
                )
            )
        ).scalar_one()
        if not others:
            raise AppError(
                code="last_owner",
                message="a project needs at least one owner; make someone else an owner first",
                status_code=409,
            )
