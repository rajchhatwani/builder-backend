"""Phase A — Organizations service.

Framework-free: takes a session and plain data, raises `AppError` on policy violations and
collisions. Mirrors `MemberService` / `ProjectService` in style.

Invariants enforced here:
  - every PlatformUser has at least one Organization (the service creates the personal one
    on sign-up — see hook in platform_auth_service);
  - every Organization has at least one `owner`;
  - a team Org on the 'free' plan may never grow past its seat cap, counting active members
    AND pending invitations (so a double-click cannot buy a free extra seat).
"""

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Text, cast, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import platform_security as sec
from app.core.naming import slugify
from app.exceptions import AppError
from app.models.enums import (
    AccountStatus,
    AuditResult,
    InvitationStatus,
    OrgKind,
    OrgRole,
    SubscriptionStatus,
)
from app.models.platform import (
    ApiToken,
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    Plan,
    PlatformUser,
    Subscription,
)
from app.models.project import Project
from app.services import audit_service
from app.services.platform_auth_service import normalize_email

INVITATION_TTL = timedelta(days=14)
DEFAULT_PERSONAL_PLAN_ID = "free"
DEFAULT_TEAM_PLAN_ID = "team"


def _now() -> datetime:
    return datetime.now(UTC)


def _new_invitation_token() -> tuple[str, str]:
    raw = "bb_inv_" + secrets.token_urlsafe(32)
    return raw, sec.hash_token(raw)


def _slug_conflict() -> AppError:
    return AppError(
        code="conflict", message="an organization with this slug already exists", status_code=409
    )


def _not_a_member() -> AppError:
    return AppError(code="not_found", message="not found", status_code=404)


@dataclass(frozen=True)
class OrgSummary:
    """A user's view of one of their orgs — the row plus their own role."""

    organization: Organization
    role: OrgRole
    member_count: int


@dataclass(frozen=True)
class InvitationSummary:
    """Projection used by the API; the organization fields are already resolved."""

    invitation: OrganizationInvitation
    organization: Organization
    status: str


class OrganizationService:
    def __init__(self, session: AsyncSession) -> None:
        self.db = session

    # -- lifecycle --------------------------------------------------------------------

    async def ensure_personal_org(self, user: PlatformUser) -> Organization:
        """Idempotent: return the user's personal org, creating it if missing.

        Called on sign-up and from the login path for pre-accounts users. The personal org
        is seeded on the 'free' plan; the user becomes its owner.
        """
        existing = (
            await self.db.execute(
                select(Organization)
                .join(
                    OrganizationMember,
                    OrganizationMember.organization_id == Organization.id,
                )
                .where(
                    Organization.kind == OrgKind.personal,
                    OrganizationMember.user_id == user.id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        base = slugify(user.email.split("@", 1)[0]) or "user"
        slug = await self._unique_slug(f"{base}-{user.id.hex[:8]}")
        org = Organization(
            name=user.name or user.email.split("@", 1)[0],
            slug=slug,
            kind=OrgKind.personal,
            created_by=user.id,
        )
        self.db.add(org)
        await self.db.flush()
        self.db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=OrgRole.owner))
        self.db.add(
            Subscription(
                organization_id=org.id,
                plan_id=DEFAULT_PERSONAL_PLAN_ID,
                status=SubscriptionStatus.active,
            )
        )
        if user.default_organization_id is None:
            user.default_organization_id = org.id
        await self.db.flush()
        return org

    async def create_team_org(
        self, user: PlatformUser, *, name: str, slug: str | None
    ) -> Organization:
        candidate = slug or slugify(name)
        if not candidate:
            raise AppError(
                code="invalid_slug", message="organization slug is required", status_code=422
            )
        org = Organization(
            name=name.strip(),
            slug=candidate,
            kind=OrgKind.team,
            created_by=user.id,
        )
        self.db.add(org)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            raise _slug_conflict() from exc
        self.db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=OrgRole.owner))
        self.db.add(
            Subscription(
                organization_id=org.id,
                plan_id=DEFAULT_TEAM_PLAN_ID,
                status=SubscriptionStatus.active,
            )
        )
        await self.db.commit()
        return org

    # -- reads ------------------------------------------------------------------------

    async def list_for_user(self, user_id: uuid.UUID) -> list[OrgSummary]:
        rows = (
            await self.db.execute(
                select(Organization, OrganizationMember.role)
                .join(
                    OrganizationMember,
                    OrganizationMember.organization_id == Organization.id,
                )
                .where(
                    OrganizationMember.user_id == user_id,
                    Organization.deleted_at.is_(None),
                )
                .order_by(Organization.created_at)
            )
        ).all()
        summaries: list[OrgSummary] = []
        for org, role in rows:
            count = (
                await self.db.execute(
                    select(func.count())
                    .select_from(OrganizationMember)
                    .where(OrganizationMember.organization_id == org.id)
                )
            ).scalar_one()
            summaries.append(OrgSummary(organization=org, role=role, member_count=count))
        return summaries

    async def get_by_slug(self, user_id: uuid.UUID, slug: str) -> OrgSummary:
        row = (
            await self.db.execute(
                select(Organization, OrganizationMember.role)
                .join(
                    OrganizationMember,
                    OrganizationMember.organization_id == Organization.id,
                )
                .where(
                    Organization.slug == slug,
                    Organization.deleted_at.is_(None),
                    OrganizationMember.user_id == user_id,
                )
            )
        ).one_or_none()
        if row is None:
            raise _not_a_member()
        org, role = row
        count = (
            await self.db.execute(
                select(func.count())
                .select_from(OrganizationMember)
                .where(OrganizationMember.organization_id == org.id)
            )
        ).scalar_one()
        return OrgSummary(organization=org, role=role, member_count=count)

    async def resolve_slug(self, slug: str) -> Organization | None:
        """Look up an org by slug without an auth check. Used by the request guard."""
        return (
            await self.db.execute(
                select(Organization).where(
                    Organization.slug == slug, Organization.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()

    async def member_role(self, user_id: uuid.UUID, organization_id: uuid.UUID) -> OrgRole | None:
        return (
            await self.db.execute(
                select(OrganizationMember.role).where(
                    OrganizationMember.organization_id == organization_id,
                    OrganizationMember.user_id == user_id,
                )
            )
        ).scalar_one_or_none()

    async def list_members(
        self, organization_id: uuid.UUID
    ) -> list[tuple[OrganizationMember, PlatformUser]]:
        rows = await self.db.execute(
            select(OrganizationMember, PlatformUser)
            .join(PlatformUser, PlatformUser.id == OrganizationMember.user_id)
            .where(OrganizationMember.organization_id == organization_id)
            .order_by(OrganizationMember.joined_at, PlatformUser.email)
        )
        return [(m, u) for m, u in rows.all()]

    async def list_projects(self, organization_id: uuid.UUID) -> list[Project]:
        rows = await self.db.execute(
            select(Project)
            .where(Project.organization_id == organization_id)
            .order_by(Project.created_at)
        )
        return list(rows.scalars())

    # -- invitations ------------------------------------------------------------------

    async def list_invitations(self, organization_id: uuid.UUID) -> list[OrganizationInvitation]:
        rows = await self.db.execute(
            select(OrganizationInvitation)
            .where(OrganizationInvitation.organization_id == organization_id)
            .order_by(OrganizationInvitation.created_at.desc())
        )
        return list(rows.scalars())

    async def list_pending_for_email(self, email: str) -> list[InvitationSummary]:
        rows = (
            await self.db.execute(
                select(OrganizationInvitation, Organization)
                .join(
                    Organization,
                    Organization.id == OrganizationInvitation.organization_id,
                )
                .where(
                    OrganizationInvitation.email == normalize_email(email),
                    OrganizationInvitation.accepted_at.is_(None),
                    OrganizationInvitation.revoked_at.is_(None),
                    OrganizationInvitation.expires_at > _now(),
                )
                .order_by(OrganizationInvitation.created_at.desc())
            )
        ).all()
        return [
            InvitationSummary(invitation=inv, organization=org, status=self._invitation_status(inv))
            for inv, org in rows
        ]

    async def create_invitation(
        self,
        organization_id: uuid.UUID,
        *,
        email: str,
        role: OrgRole,
        invited_by: uuid.UUID,
    ) -> tuple[OrganizationInvitation, str]:
        """Enforce the seat cap transactionally. Return (row, raw_token). Raw token leaves once."""
        normalized = normalize_email(email)
        # Outside the savepoint: a denial rolls back and commits its audit row. The row lock
        # it takes is held until the commit below, serializing concurrent invites.
        await self.enforce_seat_limit(organization_id, extra=1, actor_id=invited_by)
        async with self.db.begin_nested():
            existing = (
                await self.db.execute(
                    select(OrganizationInvitation).where(
                        OrganizationInvitation.organization_id == organization_id,
                        OrganizationInvitation.email == normalized,
                        OrganizationInvitation.accepted_at.is_(None),
                        OrganizationInvitation.revoked_at.is_(None),
                        OrganizationInvitation.expires_at > _now(),
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                raise AppError(
                    code="conflict",
                    message="an open invitation already exists for this address",
                    status_code=409,
                )
            # Already a member? refuse so the UI can tell the admin.
            member = (
                await self.db.execute(
                    select(OrganizationMember)
                    .join(PlatformUser, PlatformUser.id == OrganizationMember.user_id)
                    .where(
                        OrganizationMember.organization_id == organization_id,
                        PlatformUser.email == normalized,
                    )
                )
            ).scalar_one_or_none()
            if member is not None:
                raise AppError(
                    code="conflict",
                    message="this user is already a member of the organization",
                    status_code=409,
                )
            raw, digest = _new_invitation_token()
            invitation = OrganizationInvitation(
                organization_id=organization_id,
                email=normalized,
                role=role,
                token_hash=digest,
                invited_by=invited_by,
                expires_at=_now() + INVITATION_TTL,
            )
            self.db.add(invitation)
        await self.db.commit()
        return invitation, raw

    async def revoke_invitation(
        self, organization_id: uuid.UUID, invitation_id: uuid.UUID
    ) -> OrganizationInvitation:
        inv = await self.db.get(OrganizationInvitation, invitation_id)
        if inv is None or inv.organization_id != organization_id:
            raise AppError(code="not_found", message="invitation not found", status_code=404)
        if inv.accepted_at is not None:
            raise AppError(code="conflict", message="invitation already accepted", status_code=409)
        inv.revoked_at = _now()
        await self.db.commit()
        return inv

    async def accept_invitation(
        self, user: PlatformUser, token: str
    ) -> tuple[Organization, OrgRole]:
        row = (
            await self.db.execute(
                select(OrganizationInvitation).where(
                    OrganizationInvitation.token_hash == sec.hash_token(token)
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise AppError(code="invalid_token", message="invitation is invalid", status_code=404)
        if row.revoked_at is not None:
            raise AppError(code="invalid_token", message="invitation was revoked", status_code=404)
        if row.accepted_at is not None:
            raise AppError(
                code="invalid_token", message="invitation already accepted", status_code=409
            )
        if row.expires_at <= _now():
            raise AppError(code="invalid_token", message="invitation expired", status_code=410)
        if normalize_email(user.email) != row.email:
            # Addresses don't match: treat as not found rather than confirm the token exists.
            raise AppError(code="invalid_token", message="invitation is invalid", status_code=404)
        org = await self.db.get(Organization, row.organization_id)
        if org is None or org.deleted_at is not None:
            raise AppError(code="invalid_token", message="invitation is invalid", status_code=404)
        existing = await self.member_role(user.id, row.organization_id)
        if existing is None:
            # Re-check at accept time: an admin may have lowered the cap since the invite.
            # This invite is already counted as pending, so it adds nothing extra.
            await self.enforce_seat_limit(
                row.organization_id, extra=0, actor_id=user.id, actor_email=user.email
            )
            self.db.add(
                OrganizationMember(
                    organization_id=row.organization_id,
                    user_id=user.id,
                    role=row.role,
                )
            )
        row.accepted_at = _now()
        await self.db.commit()
        return org, row.role

    # -- members --------------------------------------------------------------------

    async def set_member_role(
        self,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        role: OrgRole,
    ) -> OrganizationMember:
        member = await self._require_member(organization_id, user_id)
        if member.role is OrgRole.owner and role is not OrgRole.owner:
            await self._require_another_owner(organization_id, user_id)
        member.role = role
        await self.db.commit()
        return member

    async def remove_member(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> None:
        member = await self._require_member(organization_id, user_id)
        if member.role is OrgRole.owner:
            await self._require_another_owner(organization_id, user_id)
        await self.db.delete(member)
        await self.db.commit()

    async def transfer_ownership(
        self, organization_id: uuid.UUID, from_user_id: uuid.UUID, to_user_id: uuid.UUID
    ) -> None:
        if from_user_id == to_user_id:
            return
        src = await self._require_member(organization_id, from_user_id)
        dst = await self._require_member(organization_id, to_user_id)
        if src.role is not OrgRole.owner:
            raise AppError(
                code="forbidden",
                message="only an owner can transfer ownership",
                status_code=403,
            )
        src.role = OrgRole.admin
        dst.role = OrgRole.owner
        await self.db.commit()

    async def delete_organization(self, organization_id: uuid.UUID) -> None:
        """Soft delete: the org row stays so audit trails resolve, but members and projects
        detach. Phase F wires hard-delete to a per-org GDPR export+erase job."""
        org = await self.db.get(Organization, organization_id)
        if org is None:
            raise AppError(code="not_found", message="organization not found", status_code=404)
        if org.kind is OrgKind.personal:
            raise AppError(
                code="forbidden",
                message="personal organizations cannot be deleted",
                status_code=403,
            )
        org.deleted_at = _now()
        await self.db.commit()

    # -- plan / usage ---------------------------------------------------------------

    async def plan_and_subscription(self, organization_id: uuid.UUID) -> tuple[Plan, Subscription]:
        sub = await self.db.get(Subscription, organization_id)
        if sub is None:
            raise AppError(
                code="not_found", message="organization subscription not found", status_code=404
            )
        plan = await self.db.get(Plan, sub.plan_id)
        if plan is None:  # should not happen; plan rows are seeded
            raise AppError(code="not_found", message="plan not found", status_code=500)
        return plan, sub

    async def usage(
        self, organization_id: uuid.UUID, *, viewer_id: uuid.UUID | None = None
    ) -> dict[str, int | None]:
        """Counters for the plan page. `api_tokens_used` is the viewer's own tokens in this
        org, because the API-token cap is per member (§6.2)."""
        plan, sub = await self.plan_and_subscription(organization_id)
        seats_used = await self._count_members(organization_id)
        pending = await self._count_pending_invites(organization_id)
        projects_used = await self._count_projects(organization_id)
        seats_cap = sub.seat_override if sub.seat_override is not None else plan.max_seats
        projects_cap = (
            sub.project_override if sub.project_override is not None else plan.max_projects
        )
        return {
            "seats_used": seats_used,
            "seats_cap": seats_cap,
            "pending_invites": pending,
            "projects_used": projects_used,
            "projects_cap": projects_cap,
            "api_tokens_used": (
                await self.count_active_tokens(organization_id, user_id=viewer_id)
                if viewer_id is not None
                else 0
            ),
            "api_tokens_cap": plan.max_api_tokens,
            "mcp_tokens_used": await self.count_active_tokens(organization_id, mcp_only=True),
            "mcp_tokens_cap": plan.max_mcp_tokens,
        }

    # -- internals ------------------------------------------------------------------

    # -- quota enforcement (§6.2) --------------------------------------------------------
    #
    # Every check locks the org's subscription row (SELECT ... FOR UPDATE) before counting,
    # so concurrent writes against one org serialize and a double-click cannot overshoot a
    # cap. The lock is held until the caller's transaction commits the new row. A denial
    # rolls the transaction back, writes a `quota.denied` audit row, commits it, and raises
    # a 402 whose `details` carry what the UI needs for an upgrade CTA.

    async def _locked_plan_and_subscription(
        self, organization_id: uuid.UUID
    ) -> tuple[Plan, Subscription]:
        sub = (
            await self.db.execute(
                select(Subscription)
                .where(Subscription.organization_id == organization_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if sub is None:  # fail closed: no subscription means no quota, not unlimited
            raise AppError(
                code="not_found", message="organization subscription not found", status_code=404
            )
        plan = await self.db.get(Plan, sub.plan_id)
        if plan is None:
            raise AppError(code="not_found", message="plan not found", status_code=500)
        return plan, sub

    async def _deny(
        self,
        organization_id: uuid.UUID,
        *,
        code: str,
        resource: str,
        plan: Plan,
        cap: int | None,
        used: int,
        message: str,
        actor_id: uuid.UUID | None,
        actor_email: str | None,
        reason: str = "cap",
    ) -> AppError:
        """Record the refusal in its own committed transaction and return the 402 to raise.

        `reason` is 'cap' (the plan's counter is full) or 'past_due' (payment failed, §10)."""
        plan_id = plan.id  # read before rollback expires the instances
        org = await self.db.get(Organization, organization_id)
        slug = org.slug if org is not None else None
        await self.db.rollback()
        detail: dict[str, object] = {
            "resource": resource,
            "plan": plan_id,
            "cap": cap,
            "used": used,
            "reason": reason,
        }
        await audit_service.record(
            self.db,
            action="quota.denied",
            result=AuditResult.denied,
            actor_id=actor_id,
            actor_email=actor_email,
            organization_id=organization_id,
            target_type="organization",
            target_id=organization_id,
            detail=detail,
        )
        await self.db.commit()
        # The response also names the org, so the UI can link to its Plan page.
        return AppError(
            code=code,
            message=message,
            status_code=402,
            details=[{**detail, "organization_slug": slug}],
        )

    async def _refuse_if_past_due(
        self,
        organization_id: uuid.UUID,
        sub: Subscription,
        plan: Plan,
        *,
        resource: str,
        used: int,
        actor_id: uuid.UUID | None,
        actor_email: str | None,
    ) -> None:
        """§10: while an invoice is unpaid, new seats and new projects are refused; existing
        work carries on. Applies on every plan, capped or not: this is about money."""
        if sub.status is not SubscriptionStatus.past_due:
            return
        raise await self._deny(
            organization_id,
            code="subscription_past_due",
            resource=resource,
            plan=plan,
            cap=None,
            used=used,
            message=(
                "the organization's last payment failed; update the payment method on the "
                "Plan page to add more"
            ),
            actor_id=actor_id,
            actor_email=actor_email,
            reason="past_due",
        )

    async def enforce_seat_limit(
        self,
        organization_id: uuid.UUID,
        *,
        extra: int = 1,
        actor_id: uuid.UUID | None = None,
        actor_email: str | None = None,
    ) -> None:
        """Seats = active members + pending invites. `extra` is how many this write adds:
        1 for a new invite, 0 when accepting one (it is already counted as pending)."""
        plan, sub = await self._locked_plan_and_subscription(organization_id)
        cap = sub.seat_override if sub.seat_override is not None else plan.max_seats
        used = await self._count_members(organization_id)
        used += await self._count_pending_invites(organization_id)
        await self._refuse_if_past_due(
            organization_id,
            sub,
            plan,
            resource="seats",
            used=used,
            actor_id=actor_id,
            actor_email=actor_email,
        )
        if cap is not None and used + extra > cap:
            raise await self._deny(
                organization_id,
                code="seat_limit",
                resource="seats",
                plan=plan,
                cap=cap,
                used=used,
                message=(
                    f"plan '{plan.id}' allows {cap} seat(s); you have "
                    f"{used} (members + pending invites)"
                ),
                actor_id=actor_id,
                actor_email=actor_email,
            )

    async def enforce_project_limit(
        self,
        organization_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None = None,
        actor_email: str | None = None,
    ) -> None:
        plan, sub = await self._locked_plan_and_subscription(organization_id)
        cap = sub.project_override if sub.project_override is not None else plan.max_projects
        used = await self._count_projects(organization_id)
        await self._refuse_if_past_due(
            organization_id,
            sub,
            plan,
            resource="projects",
            used=used,
            actor_id=actor_id,
            actor_email=actor_email,
        )
        if cap is not None and used + 1 > cap:
            raise await self._deny(
                organization_id,
                code="project_limit",
                resource="projects",
                plan=plan,
                cap=cap,
                used=used,
                message=f"plan '{plan.id}' allows {cap} project(s)",
                actor_id=actor_id,
                actor_email=actor_email,
            )

    async def enforce_token_limits(
        self,
        organization_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
        mcp: bool,
        actor_email: str | None = None,
    ) -> None:
        """API tokens: active tokens per user per org. MCP tokens: active tokens with any
        `mcp:*` scope per org, across all members. Both checked when `mcp` is true."""
        plan, _sub = await self._locked_plan_and_subscription(organization_id)
        if plan.max_api_tokens is not None:
            used = await self.count_active_tokens(organization_id, user_id=user_id)
            if used + 1 > plan.max_api_tokens:
                raise await self._deny(
                    organization_id,
                    code="api_token_limit",
                    resource="api_tokens",
                    plan=plan,
                    cap=plan.max_api_tokens,
                    used=used,
                    message=(
                        f"plan '{plan.id}' allows {plan.max_api_tokens} active API token(s) "
                        "per member"
                    ),
                    actor_id=user_id,
                    actor_email=actor_email,
                )
        if mcp and plan.max_mcp_tokens is not None:
            used = await self.count_active_tokens(organization_id, mcp_only=True)
            if used + 1 > plan.max_mcp_tokens:
                raise await self._deny(
                    organization_id,
                    code="mcp_token_limit",
                    resource="mcp_tokens",
                    plan=plan,
                    cap=plan.max_mcp_tokens,
                    used=used,
                    message=f"plan '{plan.id}' allows {plan.max_mcp_tokens} MCP token(s)",
                    actor_id=user_id,
                    actor_email=actor_email,
                )

    async def count_active_tokens(
        self,
        organization_id: uuid.UUID,
        *,
        user_id: uuid.UUID | None = None,
        mcp_only: bool = False,
    ) -> int:
        """A token belongs to its project's org when pinned, else to its owner's default
        org — the same rule `ApiTokenService.create` uses to pick the org it charges."""
        token_org = func.coalesce(Project.organization_id, PlatformUser.default_organization_id)
        stmt = (
            select(func.count())
            .select_from(ApiToken)
            .join(PlatformUser, PlatformUser.id == ApiToken.user_id)
            .outerjoin(Project, Project.id == ApiToken.project_id)
            .where(
                token_org == organization_id,
                ApiToken.revoked_at.is_(None),
                ApiToken.expires_at > _now(),
            )
        )
        if user_id is not None:
            stmt = stmt.where(ApiToken.user_id == user_id)
        if mcp_only:
            # scopes is a JSON list; '"mcp:' only appears inside an mcp:* scope string.
            stmt = stmt.where(cast(ApiToken.scopes, Text).like('%"mcp:%'))
        return (await self.db.execute(stmt)).scalar_one()

    async def count_members(self, organization_id: uuid.UUID) -> int:
        """Active members only (no pending invites): the seats Stripe bills for."""
        return await self._count_members(organization_id)

    async def _count_members(self, organization_id: uuid.UUID) -> int:
        return (
            await self.db.execute(
                select(func.count())
                .select_from(OrganizationMember)
                .where(OrganizationMember.organization_id == organization_id)
            )
        ).scalar_one()

    async def _count_pending_invites(self, organization_id: uuid.UUID) -> int:
        return (
            await self.db.execute(
                select(func.count())
                .select_from(OrganizationInvitation)
                .where(
                    OrganizationInvitation.organization_id == organization_id,
                    OrganizationInvitation.accepted_at.is_(None),
                    OrganizationInvitation.revoked_at.is_(None),
                    OrganizationInvitation.expires_at > _now(),
                )
            )
        ).scalar_one()

    async def _count_projects(self, organization_id: uuid.UUID) -> int:
        return (
            await self.db.execute(
                select(func.count())
                .select_from(Project)
                .where(Project.organization_id == organization_id)
            )
        ).scalar_one()

    async def _require_member(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> OrganizationMember:
        row = await self.db.get(OrganizationMember, (organization_id, user_id))
        if row is None:
            raise AppError(code="not_found", message="member not found", status_code=404)
        return row

    async def _require_another_owner(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> None:
        others = (
            await self.db.execute(
                select(func.count())
                .select_from(OrganizationMember)
                .where(
                    OrganizationMember.organization_id == organization_id,
                    OrganizationMember.role == OrgRole.owner,
                    OrganizationMember.user_id != user_id,
                )
            )
        ).scalar_one()
        if not others:
            raise AppError(
                code="last_owner",
                message=(
                    "an organization needs at least one owner; make someone else an owner first"
                ),
                status_code=409,
            )

    async def _unique_slug(self, candidate: str) -> str:
        candidate = slugify(candidate) or "org"
        base = candidate
        suffix = 0
        while True:
            exists = (
                await self.db.execute(select(Organization.id).where(Organization.slug == candidate))
            ).scalar_one_or_none()
            if exists is None:
                return candidate
            suffix += 1
            candidate = f"{base}-{suffix}"

    @staticmethod
    def _invitation_status(inv: OrganizationInvitation) -> str:
        if inv.accepted_at is not None:
            return InvitationStatus.accepted.value
        if inv.revoked_at is not None:
            return InvitationStatus.revoked.value
        if inv.expires_at <= _now():
            return InvitationStatus.expired.value
        return InvitationStatus.pending.value
