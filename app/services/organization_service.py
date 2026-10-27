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

from sqlalchemy import Text, cast, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core import platform_security as sec
from app.core.naming import slugify
from app.exceptions import AppError
from app.models.enums import (
    AuditResult,
    InvitationStatus,
    MemberRole,
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
    ProjectMember,
    Subscription,
)
from app.models.project import Project
from app.models.scim import ScimDirectory, ScimGroup, ScimUser
from app.models.sso import SsoConnection, SsoDomain, SsoLoginRequest
from app.services import audit_service
from app.services.platform_auth_service import normalize_email

INVITATION_TTL = timedelta(days=14)
DEFAULT_PERSONAL_PLAN_ID = "free"
# Owner decision: a new team org starts free and moves up only by paying (Checkout → webhook)
# or when an operator onboards it (admin plan change).
DEFAULT_TEAM_PLAN_ID = "free"
# Holding org for projects that predate accounts and have no owner yet (the migration that
# made projects.organization_id NOT NULL puts them here). No members; the bootstrap
# administrator adopts its projects into their own org.
UNCLAIMED_ORG_SLUG = "unclaimed-projects"
# Where an org lands when a platform-granted trial ends (same as a canceled Stripe plan).
EXPIRED_TRIAL_PLAN_ID = "free"


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

    async def ensure_unclaimed_org(self) -> Organization:
        org = (
            await self.db.execute(
                select(Organization).where(Organization.slug == UNCLAIMED_ORG_SLUG)
            )
        ).scalar_one_or_none()
        if org is not None:
            return org
        org = Organization(name="Unclaimed projects", slug=UNCLAIMED_ORG_SLUG, kind=OrgKind.team)
        self.db.add(org)
        await self.db.flush()
        self.db.add(
            Subscription(
                organization_id=org.id, plan_id="enterprise", status=SubscriptionStatus.active
            )
        )
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

    async def list_projects(
        self, organization_id: uuid.UUID, *, only_for_user: uuid.UUID | None = None
    ) -> list[Project]:
        """All of the org's projects, or (for plain members, §8) only those `only_for_user`
        is a member of."""
        stmt = select(Project).where(Project.organization_id == organization_id)
        if only_for_user is not None:
            stmt = stmt.where(
                Project.id.in_(
                    select(ProjectMember.project_id).where(ProjectMember.user_id == only_for_user)
                )
            )
        rows = await self.db.execute(stmt.order_by(Project.created_at))
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

    async def resend_invitation(
        self, organization_id: uuid.UUID, invitation_id: uuid.UUID, *, actor_id: uuid.UUID
    ) -> tuple[OrganizationInvitation, str]:
        """Tokens are stored hashed, so "resend" rotates: new token, new expiry, old link dead.
        An expired invite stopped counting as a seat, so reviving it is checked like a new one."""
        inv = await self.db.get(OrganizationInvitation, invitation_id)
        if inv is None or inv.organization_id != organization_id:
            raise AppError(code="not_found", message="invitation not found", status_code=404)
        if inv.accepted_at is not None or inv.revoked_at is not None:
            raise AppError(
                code="conflict", message="only a pending invitation can be resent", status_code=409
            )
        if inv.expires_at <= _now():
            await self.enforce_seat_limit(organization_id, extra=1, actor_id=actor_id)
            inv = await self.db.get(OrganizationInvitation, invitation_id)
            assert inv is not None
        raw, digest = _new_invitation_token()
        inv.token_hash = digest
        inv.expires_at = _now() + INVITATION_TTL
        await self.db.commit()
        return inv, raw

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
        return await self._accept(user, row, by_link=True)

    async def accept_invitation_by_id(
        self, user: PlatformUser, invitation_id: uuid.UUID
    ) -> tuple[Organization, OrgRole]:
        """Accept from the "pending invitations" list without the link. Sign-up never proves the
        mailbox, so this only works once the account's address is verified (the e-mailed link,
        SSO or SCIM did that); otherwise whoever registered the address first could accept."""
        row = await self.db.get(OrganizationInvitation, invitation_id)
        if user.email_verified_at is None:
            raise AppError(
                code="email_not_verified",
                message="open the link from the invitation e-mail to accept it",
                status_code=403,
            )
        return await self._accept(user, row)

    async def _accept(
        self, user: PlatformUser, row: OrganizationInvitation | None, *, by_link: bool = False
    ) -> tuple[Organization, OrgRole]:
        if row is None:
            raise AppError(code="invalid_token", message="invitation is invalid", status_code=404)
        if normalize_email(user.email) != row.email:
            # Addresses don't match: treat as not found rather than confirm it exists.
            raise AppError(code="invalid_token", message="invitation is invalid", status_code=404)
        if by_link and user.email_verified_at is None:
            user.email_verified_at = _now()  # the link only reached the real mailbox
        if row.revoked_at is not None:
            raise AppError(code="invalid_token", message="invitation was revoked", status_code=404)
        if row.accepted_at is not None:
            raise AppError(
                code="invalid_token", message="invitation already accepted", status_code=409
            )
        if row.expires_at <= _now():
            raise AppError(code="invalid_token", message="invitation expired", status_code=410)
        org = await self.db.get(Organization, row.organization_id)
        if org is None or org.deleted_at is not None or org.deletion_requested_at is not None:
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
        *,
        actor_role: OrgRole = OrgRole.owner,
    ) -> OrganizationMember:
        """§2.2/§8: admins change roles "except Owner" — only an owner may make or unmake one."""
        member = await self._require_member(organization_id, user_id)
        if OrgRole.owner in (member.role, role) and actor_role is not OrgRole.owner:
            raise await self._owner_only(organization_id)
        if member.role is OrgRole.owner and role is not OrgRole.owner:
            await self._require_another_owner(organization_id, user_id)
        member.role = role
        await self.db.commit()
        return member

    async def remove_member(
        self,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None = None,
        actor_role: OrgRole = OrgRole.owner,
    ) -> None:
        """Remove someone (or leave). Their memberships of this org's projects go with it
        (§3.2: project members must be org members)."""
        member = await self._require_member(organization_id, user_id)
        if member.role is OrgRole.owner:
            if actor_id != user_id and actor_role is not OrgRole.owner:
                raise await self._owner_only(organization_id)
            await self._require_another_owner(organization_id, user_id)
        project_ids = select(Project.id).where(Project.organization_id == organization_id)
        orphaned = await self._projects_solely_owned_by(organization_id, user_id)
        if orphaned:
            raise AppError(
                code="sole_project_owner",
                message=(
                    f"this person is the only owner of {orphaned} project(s) in the "
                    "organization; make someone else an owner of those first"
                ),
                status_code=409,
                details=[{"projects": orphaned}],
            )
        await self.db.execute(
            delete(ProjectMember).where(
                ProjectMember.user_id == user_id, ProjectMember.project_id.in_(project_ids)
            )
        )
        await self.db.delete(member)
        await self._reset_default_org(organization_id, user_id)
        await self.db.commit()

    async def _projects_solely_owned_by(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> int:
        other = aliased(ProjectMember)
        return (
            await self.db.execute(
                select(func.count())
                .select_from(ProjectMember)
                .join(Project, Project.id == ProjectMember.project_id)
                .where(
                    Project.organization_id == organization_id,
                    ProjectMember.user_id == user_id,
                    ProjectMember.role == MemberRole.owner,
                    ~select(other.user_id)
                    .where(
                        other.project_id == ProjectMember.project_id,
                        other.role == MemberRole.owner,
                        other.user_id != user_id,
                    )
                    .exists(),
                )
            )
        ).scalar_one()

    async def _reset_default_org(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Anyone whose landing org was this one lands on their personal org instead."""
        user = await self.db.get(PlatformUser, user_id)
        if user is not None and user.default_organization_id == organization_id:
            personal = await self.ensure_personal_org(user)
            user.default_organization_id = personal.id

    async def _owner_only(self, organization_id: uuid.UUID) -> AppError:
        return AppError(
            code="org_role_required",
            message="only an owner can make or remove owners",
            status_code=403,
            details=[
                {"needed_role": "owner", "owner_emails": await self.owner_emails(organization_id)}
            ],
        )

    async def owner_emails(self, organization_id: uuid.UUID) -> list[str]:
        rows = await self.db.execute(
            select(PlatformUser.email)
            .join(OrganizationMember, OrganizationMember.user_id == PlatformUser.id)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.role == OrgRole.owner,
            )
            .order_by(PlatformUser.email)
        )
        return list(rows.scalars())

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

    # -- deletion (owner decision: a request with a grace period) -------------------------

    async def request_deletion(
        self, organization_id: uuid.UUID, *, actor_id: uuid.UUID, grace_days: int
    ) -> Organization:
        """Block the org now and schedule its deletion. Refused for personal orgs and while a
        Stripe subscription is live (cancel it in the billing portal first, so nobody keeps
        being charged for a deleted org)."""
        from app.services.billing_service import has_live_stripe_subscription

        org = await self._live_org(organization_id)
        if org.kind is OrgKind.personal:
            raise AppError(
                code="forbidden",
                message="personal organizations cannot be deleted",
                status_code=403,
            )
        if org.deletion_requested_at is not None:
            raise AppError(
                code="deletion_already_requested",
                message="deletion has already been requested for this organization",
                status_code=409,
            )
        sub = await self.db.get(Subscription, organization_id)
        if sub is not None and has_live_stripe_subscription(sub):
            raise AppError(
                code="org_has_billing",
                message="cancel the organization's subscription in the billing portal first",
                status_code=409,
            )
        now = _now()
        org.deletion_requested_at = now
        org.deletion_scheduled_for = now + timedelta(days=grace_days)
        org.deletion_requested_by = actor_id
        await self.db.commit()
        return org

    async def cancel_deletion(self, organization_id: uuid.UUID) -> Organization:
        org = await self._live_org(organization_id)
        if org.deletion_requested_at is None:
            raise AppError(
                code="no_deletion_request",
                message="no deletion has been requested for this organization",
                status_code=409,
            )
        org.deletion_requested_at = None
        org.deletion_scheduled_for = None
        org.deletion_requested_by = None
        await self.db.commit()
        return org

    async def reschedule_deletion(
        self, organization_id: uuid.UUID, *, grace_days: int
    ) -> Organization:
        """Operator: give a pending request a different period, counted from now."""
        org = await self._live_org(organization_id)
        if org.deletion_requested_at is None:
            raise AppError(
                code="no_deletion_request",
                message="no deletion has been requested for this organization",
                status_code=409,
            )
        org.deletion_scheduled_for = _now() + timedelta(days=grace_days)
        await self.db.commit()
        return org

    async def execute_deletion(self, organization_id: uuid.UUID) -> int:
        """Delete a requested org: its projects (and all their data), memberships and pending
        invites. The org row stays, soft-deleted, so audit trails resolve. Returns the number
        of projects deleted. Callers check that a request exists."""
        org = await self._live_org(organization_id)
        projects = list(
            (
                await self.db.execute(select(Project).where(Project.organization_id == org.id))
            ).scalars()
        )
        for project in projects:
            await self.db.delete(project)  # entities, configs, members cascade in the DB
        member_ids = list(
            (
                await self.db.execute(
                    select(OrganizationMember.user_id).where(
                        OrganizationMember.organization_id == organization_id
                    )
                )
            ).scalars()
        )
        await self.db.execute(
            delete(OrganizationMember).where(OrganizationMember.organization_id == organization_id)
        )
        await self.db.execute(
            update(OrganizationInvitation)
            .where(
                OrganizationInvitation.organization_id == organization_id,
                OrganizationInvitation.accepted_at.is_(None),
                OrganizationInvitation.revoked_at.is_(None),
            )
            .values(revoked_at=_now())
        )
        for user_id in member_ids:
            await self._reset_default_org(organization_id, user_id)
        # Identity setup dies with the org; a verified domain must not stay claimed forever.
        for model in (
            ScimGroup,
            ScimUser,
            ScimDirectory,
            SsoLoginRequest,
            SsoDomain,
            SsoConnection,
        ):
            await self.db.execute(delete(model).where(model.organization_id == organization_id))
        org.deleted_at = _now()
        await self.db.flush()
        return len(projects)

    async def _live_org(self, organization_id: uuid.UUID) -> Organization:
        org = await self.db.get(Organization, organization_id)
        if org is None or org.deleted_at is not None:
            raise AppError(code="not_found", message="organization not found", status_code=404)
        return org

    async def rename(self, organization_id: uuid.UUID, name: str) -> Organization:
        org = await self.db.get(Organization, organization_id)
        if org is None:
            raise AppError(code="not_found", message="organization not found", status_code=404)
        org.name = name.strip()
        await self.db.commit()
        return org

    # -- org projects (§8 "Projects") ---------------------------------------------------

    async def join_project(
        self,
        organization_id: uuid.UUID,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        role: MemberRole,
    ) -> ProjectMember:
        """An org admin adds themselves to one of the org's projects."""
        project = await self.db.get(Project, project_id)
        if project is None or project.organization_id != organization_id:
            raise AppError(code="not_found", message="project not found", status_code=404)
        existing = await self.db.get(ProjectMember, (project_id, user_id))
        if existing is not None:
            raise AppError(code="conflict", message="already a member", status_code=409)
        member = ProjectMember(project_id=project_id, user_id=user_id, role=role)
        self.db.add(member)
        await self.db.commit()
        return member

    async def transfer_project(
        self,
        project_id: uuid.UUID,
        *,
        from_org_id: uuid.UUID,
        to_slug: str,
        actor: PlatformUser,
    ) -> tuple[Project, Organization]:
        """§8: move a project between two orgs the actor owns. Everyone on the project must
        already be a member of the destination, and the destination's project cap and
        billing status apply as for a new project."""
        project = await self.db.get(Project, project_id)
        if project is None or project.organization_id != from_org_id:
            raise AppError(code="not_found", message="project not found", status_code=404)
        target = await self.get_by_slug(actor.id, to_slug)  # 404 unless a member
        if target.role is not OrgRole.owner:
            raise AppError(
                code="org_role_required",
                message="you must own the destination organization",
                status_code=403,
                details=[
                    {
                        "needed_role": "owner",
                        "owner_emails": await self.owner_emails(target.organization.id),
                    }
                ],
            )
        to_org = target.organization
        if to_org.id == from_org_id:
            raise AppError(
                code="conflict",
                message="the project is already in this organization",
                status_code=409,
            )
        outsiders = (
            await self.db.execute(
                select(func.count())
                .select_from(ProjectMember)
                .where(
                    ProjectMember.project_id == project_id,
                    ~select(OrganizationMember.user_id)
                    .where(
                        OrganizationMember.organization_id == to_org.id,
                        OrganizationMember.user_id == ProjectMember.user_id,
                    )
                    .exists(),
                )
            )
        ).scalar_one()
        if outsiders:
            raise AppError(
                code="not_an_org_member",
                message=(
                    f"{outsiders} project member(s) don't belong to '{to_org.slug}'; "
                    "invite them there or remove them from the project first"
                ),
                status_code=409,
            )
        await self.enforce_project_limit(to_org.id, actor_id=actor.id, actor_email=actor.email)
        project = await self.db.get(Project, project_id)  # still locked-in transaction
        assert project is not None
        project.organization_id = to_org.id
        await self.db.commit()
        return project, to_org

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
        if await self.expire_trial_if_due(sub):
            await self.db.commit()  # the expiry stands even if this write is then refused
            return await self._locked_plan_and_subscription(organization_id)
        plan = await self.db.get(Plan, sub.plan_id)
        if plan is None:
            raise AppError(code="not_found", message="plan not found", status_code=500)
        return plan, sub

    async def expire_trial_if_due(self, sub: Subscription) -> bool:
        """A platform-granted trial (no Stripe subscription behind it) ends on its date: the
        org drops to the free plan. Soft-fail, as for a downgrade (§6.3): nothing is deleted,
        new growth past the free caps is refused. Stripe trials are Stripe's to end (C.3).
        Adds the change and its audit row to the session; the caller commits."""
        if (
            sub.status is not SubscriptionStatus.trial
            or sub.trial_ends_at is None
            or sub.trial_ends_at > _now()
            or sub.stripe_subscription_id
        ):
            return False
        old_plan = sub.plan_id
        sub.plan_id = EXPIRED_TRIAL_PLAN_ID
        sub.status = SubscriptionStatus.canceled
        await audit_service.record(
            self.db,
            action="billing.trial_expired",
            via="system",
            organization_id=sub.organization_id,
            target_type="organization",
            target_id=sub.organization_id,
            detail={"from_plan": old_plan, "to_plan": EXPIRED_TRIAL_PLAN_ID},
        )
        return True

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
        if actor_email is None and actor_id is not None:
            # The audit views show the actor's address; an id alone renders as "session".
            actor = await self.db.get(PlatformUser, actor_id)
            actor_email = actor.email if actor is not None else None
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

    async def _refuse_if_locked(self, organization_id: uuid.UUID) -> None:
        """423: an org waiting for deletion takes nothing new (projects, tokens), however the
        request reached it."""
        from app.api.security import org_deletion_pending

        org = await self.db.get(Organization, organization_id, populate_existing=True)
        if org is not None and org.deletion_requested_at is not None:
            raise org_deletion_pending(org)

    async def enforce_project_limit(
        self,
        organization_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None = None,
        actor_email: str | None = None,
    ) -> None:
        await self._refuse_if_locked(organization_id)
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
        await self._refuse_if_locked(organization_id)
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
        if mcp and not plan.allow_mcp:  # a generous cap doesn't switch the feature on
            raise await self.deny_mcp_not_in_plan(
                organization_id, plan, actor_id=user_id, actor_email=actor_email
            )

    async def deny_mcp_not_in_plan(
        self,
        organization_id: uuid.UUID,
        plan: Plan,
        *,
        actor_id: uuid.UUID | None,
        actor_email: str | None,
    ) -> AppError:
        """§6.2 `plans.allow_mcp`: MCP access follows the plan, whatever the token cap says."""
        return await self._deny(
            organization_id,
            code="mcp_not_in_plan",
            resource="mcp_tokens",
            plan=plan,
            cap=None,
            used=0,
            message=f"plan '{plan.id}' doesn't include MCP access; upgrade to use it",
            actor_id=actor_id,
            actor_email=actor_email,
            reason="feature",
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
