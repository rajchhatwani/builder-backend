"""Operations behind the admin console. Administrators manage people and see metadata; they do
not read customer specs, secrets or generated code (that is a deliberate privacy line)."""

import secrets
import string
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.exceptions import AppError
from app.models.entity import Entity
from app.models.enums import AccountStatus, AuditResult, MemberRole, PlatformRole
from app.models.platform import ApiToken, AuditLog, PlatformUser, ProjectMember
from app.models.project import Project
from app.schemas.account import AdminStats
from app.services import audit_service
from app.services.access_service import Principal
from app.services.platform_auth_service import PlatformAuthService, RequestInfo

_ALPHABET = string.ascii_letters + string.digits


def generate_temporary_password() -> str:
    """20 random characters with at least one of each class, so it passes the policy."""
    while True:
        candidate = "".join(secrets.choice(_ALPHABET) for _ in range(20))
        if (
            any(c.islower() for c in candidate)
            and any(c.isupper() for c in candidate)
            and any(c.isdigit() for c in candidate)
        ):
            return candidate


class AdminService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.db = session
        self.settings = settings

    # -- users ---------------------------------------------------------------------------

    async def list_users(
        self,
        *,
        limit: int,
        offset: int,
        query: str | None,
        status: AccountStatus | None,
        role: PlatformRole | None,
    ) -> tuple[list[tuple[PlatformUser, int]], int]:
        conditions = []
        if query:
            like = f"%{query.strip().lower()[:100]}%"
            conditions.append(
                or_(PlatformUser.email.like(like), func.lower(PlatformUser.name).like(like))
            )
        if status is not None:
            conditions.append(PlatformUser.status == status)
        if role is not None:
            conditions.append(PlatformUser.platform_role == role)
        total = (
            await self.db.execute(select(func.count()).select_from(PlatformUser).where(*conditions))
        ).scalar_one()
        projects = (
            select(func.count())
            .select_from(ProjectMember)
            .where(ProjectMember.user_id == PlatformUser.id)
            .correlate(PlatformUser)
            .scalar_subquery()
        )
        rows = await self.db.execute(
            select(PlatformUser, projects)
            .where(*conditions)
            .order_by(PlatformUser.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [(u, int(n)) for u, n in rows.all()], total

    async def get_user(self, user_id: uuid.UUID) -> tuple[PlatformUser, int]:
        user = await self.db.get(PlatformUser, user_id)
        if user is None:
            raise AppError(code="not_found", message="user not found", status_code=404)
        count = (
            await self.db.execute(
                select(func.count())
                .select_from(ProjectMember)
                .where(ProjectMember.user_id == user_id)
            )
        ).scalar_one()
        return user, int(count)

    async def create_user(
        self,
        actor: Principal,
        *,
        email: str,
        name: str,
        role: PlatformRole,
        password: str | None,
        info: RequestInfo,
    ) -> tuple[PlatformUser, str | None]:
        generated = password is None
        chosen = password if password is not None else generate_temporary_password()
        user = await PlatformAuthService(self.db, self.settings).create_user(
            email=email,
            password=chosen,
            name=name,
            role=role,
            info=info,
            must_change_password=True,  # the administrator knows the password, so it is temporary
        )
        await self._audit(actor, "admin.user_create", user, info, {"role": role.value})
        await self.db.commit()
        return user, chosen if generated else None

    async def update_user(
        self,
        actor: Principal,
        user_id: uuid.UUID,
        *,
        name: str | None,
        status: AccountStatus | None,
        role: PlatformRole | None,
        info: RequestInfo,
    ) -> PlatformUser:
        user, _ = await self.get_user(user_id)
        changes: dict[str, object] = {}
        if user.id == actor.user.id and (
            (status is not None and status is not AccountStatus.active)
            or (role is not None and role is not user.platform_role)
        ):
            raise AppError(
                code="self_change",
                message="you cannot suspend or change the role of your own account",
                status_code=409,
            )
        if name is not None and name != user.name:
            user.name = name.strip()[:100]
            changes["name"] = True
        if role is not None and role is not user.platform_role:
            if user.platform_role is PlatformRole.platform_admin:
                await self._require_another_admin(user.id)
            changes["role"] = f"{user.platform_role.value}->{role.value}"
            user.platform_role = role
            await PlatformAuthService(self.db, self.settings).revoke_all_sessions(user)
        if status is not None and status is not user.status:
            if (
                status is AccountStatus.suspended
                and user.platform_role is PlatformRole.platform_admin
            ):
                await self._require_another_admin(user.id)
            changes["status"] = status.value
            user.status = status
            if status is AccountStatus.suspended:
                await PlatformAuthService(self.db, self.settings).revoke_all_sessions(user)
        if changes:
            await self._audit(actor, "admin.user_update", user, info, changes)
        await self.db.commit()
        return user

    async def revoke_sessions(
        self, actor: Principal, user_id: uuid.UUID, info: RequestInfo
    ) -> None:
        user, _ = await self.get_user(user_id)
        await PlatformAuthService(self.db, self.settings).revoke_all_sessions(user)
        await self._audit(actor, "admin.sessions_revoke", user, info, None)
        await self.db.commit()

    async def reset_password(self, actor: Principal, user_id: uuid.UUID, info: RequestInfo) -> str:
        """Replace the password with a generated one the person must change at next sign-in."""
        user, _ = await self.get_user(user_id)
        if user.id == actor.user.id:
            raise AppError(
                code="self_change",
                message="change your own password from your account",
                status_code=409,
            )
        from app.core import platform_security as sec

        temporary = generate_temporary_password()
        user.password_hash = sec.hash_password(temporary)
        user.password_changed_at = datetime.now(UTC)
        user.must_change_password = True
        user.failed_logins = 0
        user.locked_until = None
        await PlatformAuthService(self.db, self.settings).revoke_all_sessions(user)
        await self._audit(actor, "admin.password_reset", user, info, None)
        await self.db.commit()
        return temporary

    async def _require_another_admin(self, user_id: uuid.UUID) -> None:
        others = (
            await self.db.execute(
                select(func.count())
                .select_from(PlatformUser)
                .where(
                    PlatformUser.platform_role == PlatformRole.platform_admin,
                    PlatformUser.status == AccountStatus.active,
                    PlatformUser.id != user_id,
                )
            )
        ).scalar_one()
        if not others:
            raise AppError(
                code="last_admin",
                message="the platform needs at least one active administrator",
                status_code=409,
            )

    async def _audit(
        self,
        actor: Principal,
        action: str,
        target: PlatformUser,
        info: RequestInfo,
        detail: dict[str, object] | None,
    ) -> None:
        await audit_service.record(
            self.db,
            action=action,
            actor_id=actor.user.id,
            actor_email=actor.user.email,
            target_type="user",
            target_id=target.id,
            client_ip=info.client_ip,
            request_id=info.request_id,
            detail=detail,
        )

    # -- projects, stats -----------------------------------------------------------------

    async def list_projects(
        self, *, limit: int, offset: int, query: str | None
    ) -> tuple[list[tuple[Project, list[str], int]], int]:
        conditions = []
        if query:
            like = f"%{query.strip().lower()[:100]}%"
            conditions.append(or_(func.lower(Project.name).like(like), Project.slug.like(like)))
        total = (
            await self.db.execute(select(func.count()).select_from(Project).where(*conditions))
        ).scalar_one()
        projects = (
            (
                await self.db.execute(
                    select(Project)
                    .where(*conditions)
                    .order_by(Project.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        ids = [p.id for p in projects]
        owners: dict[uuid.UUID, list[str]] = {pid: [] for pid in ids}
        counts: dict[uuid.UUID, int] = dict.fromkeys(ids, 0)
        if ids:
            for pid, email in (
                await self.db.execute(
                    select(ProjectMember.project_id, PlatformUser.email)
                    .join(PlatformUser, PlatformUser.id == ProjectMember.user_id)
                    .where(
                        ProjectMember.project_id.in_(ids), ProjectMember.role == MemberRole.owner
                    )
                    .order_by(PlatformUser.email)
                )
            ).all():
                owners[pid].append(email)
            for pid, n in (
                await self.db.execute(
                    select(Entity.project_id, func.count())
                    .where(Entity.project_id.in_(ids))
                    .group_by(Entity.project_id)
                )
            ).all():
                counts[pid] = int(n)
        return [(p, owners[p.id], counts[p.id]) for p in projects], total

    async def stats(self) -> AdminStats:
        async def count(stmt: object) -> int:
            return int((await self.db.execute(stmt)).scalar_one())  # type: ignore[call-overload]

        users = PlatformUser
        return AdminStats(
            users=await count(select(func.count()).select_from(users)),
            active_users=await count(
                select(func.count()).select_from(users).where(users.status == AccountStatus.active)
            ),
            suspended_users=await count(
                select(func.count())
                .select_from(users)
                .where(users.status == AccountStatus.suspended)
            ),
            admins=await count(
                select(func.count())
                .select_from(users)
                .where(users.platform_role == PlatformRole.platform_admin)
            ),
            projects=await count(select(func.count()).select_from(Project)),
            api_tokens=await count(
                select(func.count()).select_from(ApiToken).where(ApiToken.revoked_at.is_(None))
            ),
            failed_logins_24h=await count(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.action == "account.login_failed",
                    AuditLog.result == AuditResult.denied,
                    AuditLog.at >= datetime.now(UTC) - timedelta(hours=24),
                )
            ),
        )
