"""The per-org data export (§9, §11): everything the platform holds about one org, as plain data.

What is left out on purpose: password hashes, TOTP secrets, recovery codes, every token and token
hash, Stripe ids, IdP certificates and client secrets, the SCIM bearer, and the encrypted
credentials of any project (SMTP/SMS keys). Project specs come through `SpecService.assemble`,
which never carries secrets either. Every query is filtered by `organization_id`.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import AppError
from app.models.platform import (
    AuditLog,
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    Plan,
    PlatformUser,
    ProjectMember,
    Subscription,
)
from app.models.project import Project
from app.models.scim import ScimDirectory
from app.models.sso import SsoConnection, SsoDomain
from app.services.spec_service import SpecService

FORMAT = "builder-org-export/1"
AUDIT_LIMIT = 10_000


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class OrgExportService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def build(self, org: Organization) -> dict[str, Any]:
        members = await self._members(org.id)
        projects = await self._projects(org.id)
        audit = await self._audit(org.id)
        return {
            "format": FORMAT,
            "exported_at": datetime.now(UTC).isoformat(),
            "organization": {
                "id": str(org.id),
                "name": org.name,
                "slug": org.slug,
                "kind": org.kind.value,
                "created_at": _iso(org.created_at),
                "policies": {
                    "require_mfa": org.require_mfa,
                    "session_ttl_hours": org.session_ttl_hours,
                    "allow_impersonation": org.allow_impersonation,
                },
            },
            "plan": await self._plan(org.id),
            "members": members,
            "invitations": await self._invitations(org.id),
            "projects": projects,
            "sso": await self._sso(org.id),
            "scim": await self._scim(org.id),
            "audit": audit,
        }

    async def _plan(self, org_id: uuid.UUID) -> dict[str, Any] | None:
        sub = await self.db.get(Subscription, org_id)
        if sub is None:
            return None
        plan = await self.db.get(Plan, sub.plan_id)
        return {
            "plan_id": sub.plan_id,
            "plan_name": plan.display_name if plan else sub.plan_id,
            "status": sub.status.value,
            "current_period_end": _iso(sub.current_period_end),
            "trial_ends_at": _iso(sub.trial_ends_at),
        }

    async def _members(self, org_id: uuid.UUID) -> list[dict[str, Any]]:
        rows = await self.db.execute(
            select(OrganizationMember, PlatformUser)
            .join(PlatformUser, PlatformUser.id == OrganizationMember.user_id)
            .where(OrganizationMember.organization_id == org_id)
            .order_by(OrganizationMember.joined_at, PlatformUser.email)
        )
        return [
            {
                "user_id": str(u.id),
                "email": u.email,
                "name": u.name,
                "role": m.role.value,
                "joined_at": _iso(m.joined_at),
            }
            for m, u in rows.all()
        ]

    async def _invitations(self, org_id: uuid.UUID) -> list[dict[str, Any]]:
        rows = await self.db.execute(
            select(OrganizationInvitation)
            .where(OrganizationInvitation.organization_id == org_id)
            .order_by(OrganizationInvitation.created_at)
        )
        return [
            {
                "email": i.email,
                "role": i.role.value,
                "created_at": _iso(i.created_at),
                "expires_at": _iso(i.expires_at),
                "accepted_at": _iso(i.accepted_at),
                "revoked_at": _iso(i.revoked_at),
            }
            for i in rows.scalars()
        ]

    async def _projects(self, org_id: uuid.UUID) -> list[dict[str, Any]]:
        projects = (
            await self.db.execute(
                select(Project)
                .where(Project.organization_id == org_id)
                .order_by(Project.created_at)
            )
        ).scalars()
        out: list[dict[str, Any]] = []
        for p in list(projects):
            people = await self.db.execute(
                select(ProjectMember.role, PlatformUser.email)
                .join(PlatformUser, PlatformUser.id == ProjectMember.user_id)
                .where(ProjectMember.project_id == p.id)
                .order_by(PlatformUser.email)
            )
            spec: dict[str, Any] | None
            error: str | None = None
            try:
                spec = (await SpecService(self.db).assemble(p.id)).model_dump(mode="json")
            except AppError as exc:  # a half-built project must not stop the export
                spec, error = None, exc.code
            out.append(
                {
                    "id": str(p.id),
                    "name": p.name,
                    "slug": p.slug,
                    "description": p.description,
                    "created_at": _iso(p.created_at),
                    "updated_at": _iso(p.updated_at),
                    "members": [
                        {"email": email, "role": role.value} for role, email in people.all()
                    ],
                    "spec": spec,
                    **({"spec_error": error} if error else {}),
                }
            )
        return out

    async def _sso(self, org_id: uuid.UUID) -> dict[str, Any] | None:
        conn = (
            await self.db.execute(
                select(SsoConnection).where(SsoConnection.organization_id == org_id)
            )
        ).scalar_one_or_none()
        domains = (
            await self.db.execute(
                select(SsoDomain)
                .where(SsoDomain.organization_id == org_id)
                .order_by(SsoDomain.domain)
            )
        ).scalars()
        domain_rows = [{"domain": d.domain, "verified_at": _iso(d.verified_at)} for d in domains]
        if conn is None and not domain_rows:
            return None
        return {
            "protocol": conn.protocol if conn else None,
            "active": bool(conn and conn.active),
            "jit_enabled": bool(conn and conn.jit_enabled),
            "jit_role": conn.jit_role if conn else None,
            "domains": domain_rows,
        }

    async def _scim(self, org_id: uuid.UUID) -> dict[str, Any] | None:
        d = await self.db.get(ScimDirectory, org_id)
        if d is None:
            return None
        return {
            "active": d.active,
            "group_roles": d.group_roles,
            "created_at": _iso(d.created_at),
            "last_sync_at": _iso(d.last_sync_at),
        }

    async def _audit(self, org_id: uuid.UUID) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(AuditLog)
                .where(AuditLog.organization_id == org_id)
                .order_by(AuditLog.id)
                .limit(AUDIT_LIMIT)
            )
        ).scalars()
        return [
            {
                "at": _iso(r.at),
                "action": r.action,
                "result": r.result.value,
                "via": r.via,
                "actor_email": r.actor_email,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "project_id": str(r.project_id) if r.project_id else None,
                "detail": r.detail,
            }
            for r in rows
        ]
