import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import platform_authz as authz
from app.core import platform_security as sec
from app.exceptions import AppError
from app.models.enums import MemberRole
from app.models.platform import ApiToken, PlatformUser
from app.services import access_service, audit_service
from app.services.platform_auth_service import RequestInfo

MAX_ACTIVE_TOKENS_PER_USER = 25


class ApiTokenService:
    def __init__(self, session: AsyncSession) -> None:
        self.db = session

    async def create(
        self,
        user: PlatformUser,
        *,
        name: str,
        description: str | None = None,
        scopes: list[str],
        expires_in_days: int,
        project_id: uuid.UUID | None,
        info: RequestInfo,
    ) -> tuple[ApiToken, str]:
        unknown = sorted(set(scopes) - authz.VALID_SCOPES)
        if unknown:
            raise AppError(
                code="invalid_scope",
                message=f"unknown scope(s): {', '.join(unknown)}",
                status_code=422,
            )
        if project_id is not None:
            # A token can only be pinned to a project its creator can already change.
            role = await access_service.member_role(self.db, user.id, project_id)
            if role is None:
                raise AppError(code="not_found", message="project not found", status_code=404)
            if (
                access_service.ROLE_LEVEL[role] < access_service.ROLE_LEVEL[MemberRole.editor]
                and authz.SCOPE_WRITE in scopes
            ):
                raise AppError(
                    code="forbidden",
                    message="viewers cannot create write tokens",
                    status_code=403,
                )
        active = (
            await self.db.execute(
                select(func.count())
                .select_from(ApiToken)
                .where(
                    ApiToken.user_id == user.id,
                    ApiToken.revoked_at.is_(None),
                    ApiToken.expires_at > datetime.now(UTC),
                )
            )
        ).scalar_one()
        if active >= MAX_ACTIVE_TOKENS_PER_USER:
            raise AppError(
                code="too_many_tokens",
                message=f"at most {MAX_ACTIVE_TOKENS_PER_USER} active tokens; revoke one first",
                status_code=409,
            )
        await self._enforce_plan_limits(user, scopes=scopes, project_id=project_id)
        raw, public_id, digest = sec.new_api_token()
        row = ApiToken(
            user_id=user.id,
            name=name.strip(),
            description=description.strip() if description else None,
            public_id=public_id,
            token_hash=digest,
            scopes=sorted(set(scopes)),
            project_id=project_id,
            expires_at=datetime.now(UTC) + timedelta(days=expires_in_days),
        )
        self.db.add(row)
        await audit_service.record(
            self.db,
            action="token.create",
            actor_id=user.id,
            actor_email=user.email,
            target_type="api_token",
            target_id=public_id,
            project_id=project_id,
            client_ip=info.client_ip,
            request_id=info.request_id,
            detail={"scopes": ",".join(row.scopes), "expires_in_days": expires_in_days},
        )
        await self.db.commit()
        return row, raw

    async def _enforce_plan_limits(
        self, user: PlatformUser, *, scopes: list[str], project_id: uuid.UUID | None
    ) -> None:
        """§6.2: charge the token to its project's org when pinned, else to the user's
        default org (`OrganizationService.count_active_tokens` uses the same rule)."""
        from app.models.project import Project
        from app.services.organization_service import OrganizationService

        orgs = OrganizationService(self.db)
        if project_id is not None:
            project = await self.db.get(Project, project_id)
            organization_id = project.organization_id if project is not None else None
        else:
            organization_id = user.default_organization_id
            if organization_id is None:  # an account predating Phase A
                organization_id = (await orgs.ensure_personal_org(user)).id
        if organization_id is None:  # a legacy project with no org yet: nothing to charge
            return
        await orgs.enforce_token_limits(
            organization_id,
            user_id=user.id,
            mcp=any(s.startswith("mcp:") for s in scopes),
            actor_email=user.email,
        )

    async def list_tokens(self, user: PlatformUser) -> list[ApiToken]:
        rows = await self.db.execute(
            select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at.desc())
        )
        return list(rows.scalars())

    async def revoke(self, user: PlatformUser, token_id: uuid.UUID, info: RequestInfo) -> None:
        row = await self.db.get(ApiToken, token_id)
        if row is None or row.user_id != user.id:
            raise AppError(code="not_found", message="token not found", status_code=404)
        if row.revoked_at is None:
            row.revoked_at = datetime.now(UTC)
            await audit_service.record(
                self.db,
                action="token.revoke",
                actor_id=user.id,
                actor_email=user.email,
                target_type="api_token",
                target_id=row.public_id,
                client_ip=info.client_ip,
                request_id=info.request_id,
            )
            await self.db.commit()

    # -- project-scoped token management (project owners) --------------------------------

    async def list_for_project(
        self, project_id: uuid.UUID
    ) -> list[tuple[ApiToken, PlatformUser]]:
        """All active tokens explicitly pinned to this project. Owner-only endpoint."""
        from app.models.platform import PlatformUser as _User

        rows = await self.db.execute(
            select(ApiToken, _User)
            .join(_User, _User.id == ApiToken.user_id)
            .where(
                ApiToken.project_id == project_id,
                ApiToken.revoked_at.is_(None),
                ApiToken.expires_at > datetime.now(UTC),
            )
            .order_by(ApiToken.created_at.desc())
        )
        return [(tok, usr) for tok, usr in rows.all()]

    async def revoke_for_project(
        self,
        actor: PlatformUser,
        project_id: uuid.UUID,
        token_id: uuid.UUID,
        info: RequestInfo,
    ) -> None:
        """Project owner revokes a token pinned to their project."""
        row = await self.db.get(ApiToken, token_id)
        if row is None or row.project_id != project_id:
            raise AppError(code="not_found", message="token not found", status_code=404)
        if row.revoked_at is None:
            row.revoked_at = datetime.now(UTC)
            await audit_service.record(
                self.db,
                action="token.revoke_by_owner",
                actor_id=actor.id,
                actor_email=actor.email,
                target_type="api_token",
                target_id=row.public_id,
                project_id=project_id,
                client_ip=info.client_ip,
                request_id=info.request_id,
            )
            await self.db.commit()

    # -- admin token management ----------------------------------------------------------

    async def list_for_user_admin(self, user_id: uuid.UUID) -> list[ApiToken]:
        """Platform admins: list all tokens for any user."""
        rows = await self.db.execute(
            select(ApiToken)
            .where(ApiToken.user_id == user_id)
            .order_by(ApiToken.created_at.desc())
        )
        return list(rows.scalars())

    async def revoke_admin(
        self,
        actor: PlatformUser,
        user_id: uuid.UUID,
        token_id: uuid.UUID,
        info: RequestInfo,
    ) -> None:
        """Platform admin revokes any token."""
        row = await self.db.get(ApiToken, token_id)
        if row is None or row.user_id != user_id:
            raise AppError(code="not_found", message="token not found", status_code=404)
        if row.revoked_at is None:
            row.revoked_at = datetime.now(UTC)
            await audit_service.record(
                self.db,
                action="admin.token_revoke",
                actor_id=actor.id,
                actor_email=actor.email,
                target_type="api_token",
                target_id=row.public_id,
                project_id=row.project_id,
                client_ip=info.client_ip,
                request_id=info.request_id,
                detail={"target_user_id": str(user_id)},
            )
            await self.db.commit()
