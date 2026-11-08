"""Impersonation (§4.5, §7.1): an operator "views as" a member of an org that consented.

The access token only *names* an `impersonation_sessions` row (`imp_sid`) and its operator
(`imp_by`). Whether the session still runs, whether the org still consents and whether writes are
switched on is read from the database on every request (see access_service), so ending a session
or turning the policy off works at once. Nothing here ever stores or logs a token.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import platform_security as sec
from app.exceptions import AppError
from app.models.enums import AccountStatus, AuditResult, PlatformRole
from app.models.platform import (
    ImpersonationSession,
    Organization,
    OrganizationMember,
    PlatformUser,
)
from app.services import audit_service
from app.services.access_service import Principal
from app.services.platform_auth_service import RequestInfo


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Started:
    session: ImpersonationSession
    access_token: str
    expires_in: int
    user: PlatformUser
    organization: Organization


def _not_found() -> AppError:
    return AppError(code="not_found", message="not found", status_code=404)


class ImpersonationService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    async def start(
        self,
        operator: Principal,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        reason: str,
        info: RequestInfo,
    ) -> Started:
        org = await self.db.get(Organization, org_id)
        if org is None or org.deleted_at is not None:
            raise _not_found()
        target = await self.db.get(PlatformUser, user_id)
        membership = await self.db.get(OrganizationMember, (org_id, user_id))
        # Staff are never viewed as (they hold the keys), and neither are people outside the org.
        if (
            target is None
            or membership is None
            or target.platform_role is not PlatformRole.customer
            or target.status is not AccountStatus.active
        ):
            raise _not_found()
        if not org.allow_impersonation:
            await audit_service.record(
                self.db,
                action="impersonation.denied",
                result=AuditResult.denied,
                actor_id=operator.user.id,
                actor_email=operator.user.email,
                organization_id=org.id,
                target_type="user",
                target_id=target.id,
                client_ip=info.client_ip,
                request_id=info.request_id,
                detail={"why": "org_policy"},
            )
            await self.db.commit()
            raise AppError(
                code="impersonation_disabled",
                message=f"{org.name} has not allowed platform staff to view as its members",
                status_code=403,
            )
        now = _now()
        ttl = self.settings.impersonation_minutes * 60
        row = ImpersonationSession(
            operator_id=operator.user.id,
            target_user_id=target.id,
            organization_id=org.id,
            reason=reason,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl),
        )
        self.db.add(row)
        await self.db.flush()
        await audit_service.record(
            self.db,
            action="impersonation.started",
            actor_id=operator.user.id,
            actor_email=operator.user.email,
            organization_id=org.id,
            target_type="user",
            target_id=target.id,
            client_ip=info.client_ip,
            request_id=info.request_id,
            detail={"reason": reason, "session_id": str(row.id), "ttl_seconds": ttl},
        )
        await self.db.commit()
        token = sec.encode_jwt(
            sec.access_claims(
                user_id=str(target.id),
                audience=sec.AUDIENCE_APP,
                token_version=target.token_version,
                ttl_seconds=ttl,
                amr=sorted(operator.auth_methods) or None,
                extra={"imp_sid": str(row.id), "imp_by": str(operator.user.id)},
            )
        )
        return Started(row, token, ttl, target, org)

    async def _get(self, session_id: uuid.UUID) -> ImpersonationSession:
        row = await self.db.get(ImpersonationSession, session_id)
        if row is None:
            raise _not_found()
        return row

    async def end(
        self,
        session_id: uuid.UUID,
        *,
        by: Principal,
        why: str,
        info: RequestInfo,
    ) -> None:
        row = await self._get(session_id)
        if row.ended_at is not None:
            return
        row.ended_at = _now()
        await self._audit_ended(row, by.user, why, info)
        await self.db.commit()

    async def end_all_for_org(self, org_id: uuid.UUID, *, by: PlatformUser, why: str) -> int:
        """Consent withdrawn: close every running session of this org (no commit)."""
        now = _now()
        rows = (
            await self.db.execute(
                select(ImpersonationSession).where(
                    ImpersonationSession.organization_id == org_id,
                    ImpersonationSession.ended_at.is_(None),
                    ImpersonationSession.expires_at > now,
                )
            )
        ).scalars()
        count = 0
        for row in rows:
            row.ended_at = now
            await self._audit_ended(row, by, why, RequestInfo())
            count += 1
        return count

    async def _audit_ended(
        self, row: ImpersonationSession, actor: PlatformUser, why: str, info: RequestInfo
    ) -> None:
        await audit_service.record(
            self.db,
            action="impersonation.ended",
            actor_id=actor.id,
            actor_email=actor.email,
            organization_id=row.organization_id,
            target_type="user",
            target_id=row.target_user_id,
            client_ip=info.client_ip,
            request_id=info.request_id,
            detail={"why": why, "session_id": str(row.id), "operator_id": str(row.operator_id)},
        )

    async def set_writes(
        self, principal: Principal, enabled: bool, info: RequestInfo
    ) -> ImpersonationSession:
        """The operator's explicit, short, audited "allow writes" switch."""
        assert principal.impersonation is not None
        row = await self._get(principal.impersonation.session_id)
        now = _now()
        if enabled:
            row.writes_until = min(
                row.expires_at, now + timedelta(minutes=self.settings.impersonation_write_minutes)
            )
        else:
            row.writes_until = None
        await audit_service.record(
            self.db,
            action="impersonation.writes_enabled" if enabled else "impersonation.writes_disabled",
            via="impersonation",
            actor_id=principal.user.id,
            actor_email=principal.user.email,
            organization_id=row.organization_id,
            target_type="user",
            target_id=row.target_user_id,
            client_ip=info.client_ip,
            request_id=info.request_id,
            detail={
                "impersonator_id": str(row.operator_id),
                "session_id": str(row.id),
                "writes_until": row.writes_until.isoformat() if row.writes_until else None,
            },
        )
        await self.db.commit()
        return row

    async def sessions(
        self, *, limit: int, offset: int, organization_id: uuid.UUID | None = None
    ) -> tuple[list[tuple[ImpersonationSession, str, str, str]], int]:
        """Newest first, with operator e-mail, member e-mail and org slug."""
        from sqlalchemy import func
        from sqlalchemy.orm import aliased

        op, target = aliased(PlatformUser), aliased(PlatformUser)
        where = []
        if organization_id is not None:
            where.append(ImpersonationSession.organization_id == organization_id)
        total = (
            await self.db.execute(
                select(func.count()).select_from(ImpersonationSession).where(*where)
            )
        ).scalar_one()
        rows = await self.db.execute(
            select(ImpersonationSession, op.email, target.email, Organization.slug)
            .join(op, op.id == ImpersonationSession.operator_id)
            .join(target, target.id == ImpersonationSession.target_user_id)
            .join(Organization, Organization.id == ImpersonationSession.organization_id)
            .where(*where)
            .order_by(ImpersonationSession.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [(r[0], r[1], r[2], r[3]) for r in rows.all()], int(total)
