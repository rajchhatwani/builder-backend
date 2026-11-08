"""SCIM 2.0 directory sync per organization (PLATFORM_SAAS_PLAN §4.3, §12.E).

Setup (org admins): one bearer token per org, shown once, stored as SHA-256 only; on/off; the
group -> role dictionary (§12.E.3). Creating the directory is gated on `plans.allow_scim` with the
usual 402 + `quota.denied` (§6.2). Operators can rotate the token away (§12.E.4) but never see one.

Provisioning (the IdP, with the bearer; the org comes from the token, never from the URL):
  - a user may only be provisioned on an e-mail domain **this** org has verified in DNS (the rule
    SSO already uses), never a platform staff account; an existing Builder account on that domain
    is linked, not duplicated;
  - creating or reactivating a user takes a seat (§6.2 "SCIM create"), and Stripe seats follow;
  - `active: false` (and DELETE) is the offboarding path of §4.3: the org membership and this
    org's project memberships go, API tokens pinned to this org's projects are revoked, and the
    person is signed out everywhere (sessions + `token_version`). Their personal org and other
    orgs stay. Projects only they owned are handed to an org owner first, so none is orphaned;
  - groups only change roles when the dictionary maps them; the last owner is never demoted or
    removed by the directory.
Accounts SCIM creates have no password: they sign in through the org's SSO.
"""

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import platform_security as sec
from app.core.platform_authz import ORG_ROLE_LEVEL
from app.exceptions import AppError
from app.models.enums import AccountStatus, AuditResult, MemberRole, OrgKind, OrgRole, PlatformRole
from app.models.platform import (
    ApiToken,
    Organization,
    OrganizationMember,
    PlatformUser,
    ProjectMember,
)
from app.models.project import Project
from app.models.scim import ScimDirectory, ScimGroup, ScimGroupMember, ScimUser
from app.models.sso import SsoDomain
from app.services import audit_service
from app.services import scim_protocol as proto
from app.services.organization_service import OrganizationService
from app.services.platform_auth_service import PlatformAuthService, RequestInfo
from app.services.scim_protocol import ScimError

TOKEN_PREFIX = "bb_scim_"
SCIM_PATH = "/scim/v2"


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def new_token() -> tuple[str, str]:
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return raw, sec.hash_token(raw)


def _not_found(kind: str) -> ScimError:
    return ScimError(404, f"{kind} not found")


def _uuid(raw: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError):
        return None


@dataclass(frozen=True)
class ScimContext:
    directory: ScimDirectory
    org: Organization
    info: RequestInfo


class ScimService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.db = session
        self.settings = settings
        self.orgs = OrganizationService(session)
        # Set by provisioning writes that changed the member count: the API calls
        # BillingService.sync_seats after the commit (like invite accept and SSO JIT do).
        self.seats_changed = False

    def base_url(self) -> str:
        return self.settings.public_api_url.rstrip("/") + SCIM_PATH

    # == setup (org admins) =======================================================================

    async def directory(self, organization_id: uuid.UUID) -> ScimDirectory | None:
        return await self.db.get(ScimDirectory, organization_id)

    async def allowed_by_plan(self, organization_id: uuid.UUID) -> bool:
        plan, _sub = await self.orgs.plan_and_subscription(organization_id)
        return plan.allow_scim

    async def _require_allowed(self, org: Organization, actor: PlatformUser) -> None:
        if org.kind is OrgKind.personal:
            raise AppError(
                code="scim_not_for_personal_orgs",
                message="SCIM is for team organizations; create one first",
                status_code=409,
            )
        plan, _sub = await self.orgs.plan_and_subscription(org.id)
        if not plan.allow_scim:
            raise await self.orgs._deny(  # noqa: SLF001 — the one shared 402 path
                org.id,
                code="scim_not_in_plan",
                resource="scim",
                plan=plan,
                cap=None,
                used=0,
                message=f"plan '{plan.id}' doesn't include SCIM provisioning; upgrade to use it",
                actor_id=actor.id,
                actor_email=actor.email,
                reason="feature",
            )

    async def issue_token(
        self, org: Organization, actor: PlatformUser, info: RequestInfo
    ) -> tuple[ScimDirectory, str, bool]:
        """Create the directory (switched on) or rotate its token. The old token stops at once;
        after an operator rotation the directory is switched back on.
        Returns (directory, raw token — shown once, created?)."""
        await self._require_allowed(org, actor)
        raw, digest = new_token()
        directory = await self.directory(org.id)
        created = directory is None
        # An empty hint means an operator rotated the token away (operator_rotate). That switch-off
        # only kept the unseen token unusable, so a fresh token switches SCIM back on. An admin's
        # own "off" (hint present) is kept.
        after_operator_rotation = directory is not None and not directory.token_hint
        if directory is None:
            directory = ScimDirectory(
                organization_id=org.id, created_by=actor.id, group_roles={}, active=True
            )
            self.db.add(directory)
        directory.bearer_hash = digest
        directory.token_hint = raw[-4:]
        directory.token_created_at = _now()
        if created or after_operator_rotation:
            directory.active = True
        await self._audit_admin(
            org, actor, info, "scim.directory_created" if created else "scim.token_rotated"
        )
        await self.db.commit()
        return directory, raw, created

    async def update(
        self,
        org: Organization,
        *,
        actor: PlatformUser,
        actor_role: OrgRole,
        active: bool | None,
        group_roles: dict[str, str] | None,
        info: RequestInfo,
    ) -> ScimDirectory:
        directory = await self._require_directory(org)
        detail: dict[str, object] = {}
        if active is not None and active != directory.active:
            if active:
                await self._require_allowed(org, actor)
                directory = await self._require_directory(org)
            directory.active = active
            detail["active"] = active
        if group_roles is not None:
            mapping = normalize_group_roles(group_roles)
            # §2.2: only an owner may make owners, so only an owner may map a group to owner.
            touches_owner = OrgRole.owner.value in mapping.values() or (
                OrgRole.owner.value in (directory.group_roles or {}).values()
            )
            if touches_owner and actor_role is not OrgRole.owner:
                raise AppError(
                    code="org_role_required",
                    message="only an owner can map a group to the owner role",
                    status_code=403,
                    details=[
                        {
                            "needed_role": "owner",
                            "owner_emails": await self.orgs.owner_emails(org.id),
                        }
                    ],
                )
            directory.group_roles = mapping
            detail["group_roles"] = len(mapping)
        if detail:
            await self._audit_admin(org, actor, info, "scim.directory_updated", detail=detail)
            if group_roles is not None:
                await self._sync_roles(org, None)
            await self.db.commit()
        return directory

    async def delete_directory(
        self, org: Organization, actor: PlatformUser, info: RequestInfo
    ) -> None:
        """Remove the directory and its resources. Org memberships stay as they are."""
        directory = await self._require_directory(org)
        await self.db.execute(delete(ScimGroup).where(ScimGroup.organization_id == org.id))
        await self.db.execute(delete(ScimUser).where(ScimUser.organization_id == org.id))
        await self.db.delete(directory)
        await self._audit_admin(org, actor, info, "scim.directory_deleted")
        await self.db.commit()

    async def operator_rotate(
        self, org: Organization, actor: PlatformUser, reason: str, info: RequestInfo
    ) -> ScimDirectory:
        """§12.E.4: an operator rotates the token away (a leaked token, say). The new token is
        never shown to anyone (§7.1), so the directory is off until an org admin issues one."""
        directory = await self._require_directory(org)
        _raw, digest = new_token()
        directory.bearer_hash = digest
        directory.token_hint = ""
        directory.token_created_at = _now()
        directory.active = False
        await audit_service.record(
            self.db,
            action="admin.scim_token_rotated",
            actor_id=actor.id,
            actor_email=actor.email,
            organization_id=org.id,
            target_type="organization",
            target_id=org.id,
            client_ip=info.client_ip,
            request_id=info.request_id,
            detail={"reason": reason},
        )
        await self.db.commit()
        return directory

    async def _require_directory(self, org: Organization) -> ScimDirectory:
        directory = await self.directory(org.id)
        if directory is None:
            raise AppError(
                code="scim_not_configured",
                message="SCIM isn't set up for this organization; generate a token first",
                status_code=409,
            )
        return directory

    async def summary(self, organization_id: uuid.UUID) -> dict[str, object]:
        users = (
            await self.db.execute(
                select(ScimUser.active, func.count())
                .where(ScimUser.organization_id == organization_id)
                .group_by(ScimUser.active)
            )
        ).all()
        counts = {bool(a): int(n) for a, n in users}
        groups = (
            await self.db.execute(
                select(ScimGroup.display_name, func.count(ScimGroupMember.scim_user_id))
                .outerjoin(ScimGroupMember, ScimGroupMember.group_id == ScimGroup.id)
                .where(ScimGroup.organization_id == organization_id)
                .group_by(ScimGroup.id, ScimGroup.display_name)
                .order_by(func.lower(ScimGroup.display_name))
            )
        ).all()
        return {
            "active_users": counts.get(True, 0),
            "deactivated_users": counts.get(False, 0),
            "groups": [(name, int(n)) for name, n in groups],
        }

    async def _audit_admin(
        self,
        org: Organization,
        actor: PlatformUser,
        info: RequestInfo,
        action: str,
        detail: dict[str, object] | None = None,
    ) -> None:
        await audit_service.record(
            self.db,
            action=action,
            actor_id=actor.id,
            actor_email=actor.email,
            organization_id=org.id,
            target_type="organization",
            target_id=org.id,
            client_ip=info.client_ip,
            request_id=info.request_id,
            detail=detail,
        )

    # == authentication (the IdP) =================================================================

    async def authenticate(self, token: str | None, info: RequestInfo) -> ScimContext:
        if not token or not token.startswith(TOKEN_PREFIX) or len(token) > 100:
            raise ScimError(401, "a valid SCIM bearer token is required")
        directory = (
            await self.db.execute(
                select(ScimDirectory).where(ScimDirectory.bearer_hash == sec.hash_token(token))
            )
        ).scalar_one_or_none()
        if directory is None or not directory.active:
            raise ScimError(401, "a valid SCIM bearer token is required")
        org = await self.db.get(Organization, directory.organization_id)
        if org is None or org.deleted_at is not None:
            raise ScimError(401, "a valid SCIM bearer token is required")
        if org.deletion_requested_at is not None:
            raise ScimError(403, "this organization is scheduled for deletion and is locked")
        if not await self.allowed_by_plan(org.id):
            raise ScimError(403, "the organization's plan doesn't include SCIM provisioning")
        directory.last_sync_at = _now()
        await self.db.commit()
        return ScimContext(directory=directory, org=org, info=info)

    # == users ====================================================================================

    async def _user_rows(
        self, org_id: uuid.UUID, *conditions: object, start: int = 1, count: int | None = None
    ) -> tuple[list[tuple[ScimUser, PlatformUser]], int]:
        base = (
            select(ScimUser, PlatformUser)
            .join(PlatformUser, PlatformUser.id == ScimUser.user_id)
            .where(ScimUser.organization_id == org_id, *conditions)  # type: ignore[arg-type]
        )
        total = (
            await self.db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        query = base.order_by(ScimUser.created_at, ScimUser.id).offset(start - 1)
        if count is not None:
            query = query.limit(count)
        rows = [(su, u) for su, u in (await self.db.execute(query)).all()]
        return rows, int(total)

    async def _groups_of(self, scim_user_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[ScimGroup]]:
        out: dict[uuid.UUID, list[ScimGroup]] = {}
        if not scim_user_ids:
            return out
        rows = await self.db.execute(
            select(ScimGroupMember.scim_user_id, ScimGroup)
            .join(ScimGroup, ScimGroup.id == ScimGroupMember.group_id)
            .where(ScimGroupMember.scim_user_id.in_(scim_user_ids))
            .order_by(func.lower(ScimGroup.display_name))
        )
        for uid, group in rows.all():
            out.setdefault(uid, []).append(group)
        return out

    def _user_resource(
        self, su: ScimUser, user: PlatformUser, groups: list[ScimGroup]
    ) -> dict[str, object]:
        return proto.user_resource(
            base_url=self.base_url(),
            id=str(su.id),
            user_name=su.user_name,
            email=user.email,
            external_id=su.external_id,
            given_name=su.given_name,
            family_name=su.family_name,
            display_name=su.display_name,
            active=su.active,
            groups=[(str(g.id), g.display_name) for g in groups],
            created=_iso(su.created_at),
            last_modified=_iso(su.updated_at),
        )

    async def list_users(
        self, ctx: ScimContext, filter_text: str | None, start: int, count: int
    ) -> dict[str, object]:
        conditions: list[object] = []
        if filter_text:
            f = proto.parse_filter(filter_text, proto.USER_FILTER_ATTRS)
            if f.attr == "username":
                conditions.append(func.lower(ScimUser.user_name) == f.value.lower())
            elif f.attr == "externalid":
                conditions.append(ScimUser.external_id == f.value)
            elif f.attr == "emails.value":
                conditions.append(PlatformUser.email == f.value.strip().lower())
            else:  # id
                sid = _uuid(f.value)
                if sid is None:
                    return proto.list_response([], total=0, start_index=start)
                conditions.append(ScimUser.id == sid)
        rows, total = await self._user_rows(ctx.org.id, *conditions, start=start, count=count)
        groups = await self._groups_of([su.id for su, _ in rows])
        return proto.list_response(
            [self._user_resource(su, u, groups.get(su.id, [])) for su, u in rows],
            total=total,
            start_index=start,
        )

    async def _one_user(self, ctx: ScimContext, raw_id: str) -> tuple[ScimUser, PlatformUser]:
        sid = _uuid(raw_id)
        if sid is None:
            raise _not_found("user")
        rows, _ = await self._user_rows(ctx.org.id, ScimUser.id == sid)
        if not rows:
            raise _not_found("user")
        return rows[0]

    async def get_user(self, ctx: ScimContext, raw_id: str) -> dict[str, object]:
        su, user = await self._one_user(ctx, raw_id)
        groups = await self._groups_of([su.id])
        return self._user_resource(su, user, groups.get(su.id, []))

    async def _require_domain(self, org: Organization, email: str) -> None:
        domain = email.rsplit("@", 1)[1]
        verified = (
            await self.db.execute(
                select(SsoDomain).where(
                    SsoDomain.domain == domain,
                    SsoDomain.organization_id == org.id,
                    SsoDomain.verified_at.is_not(None),
                )
            )
        ).scalar_one_or_none()
        if verified is None:
            raise ScimError(
                400,
                f"'{domain}' isn't a verified domain of this organization; verify it under "
                "SSO & SCIM first",
                "invalidValue",
            )

    async def _user_name_taken(
        self, org_id: uuid.UUID, user_name: str, except_id: uuid.UUID | None = None
    ) -> bool:
        conditions = [
            ScimUser.organization_id == org_id,
            func.lower(ScimUser.user_name) == user_name.lower(),
        ]
        if except_id is not None:
            conditions.append(ScimUser.id != except_id)
        return (await self.db.execute(select(ScimUser.id).where(*conditions))).first() is not None

    async def create_user(self, ctx: ScimContext, body: object) -> dict[str, object]:
        data = proto.parse_user(body)
        org = ctx.org
        await self._require_domain(org, data.email)
        if await self._user_name_taken(org.id, data.user_name):
            raise ScimError(409, "a user with this userName already exists", "uniqueness")
        user = (
            await self.db.execute(select(PlatformUser).where(PlatformUser.email == data.email))
        ).scalar_one_or_none()
        if user is not None:
            if user.platform_role is not PlatformRole.customer:
                raise ScimError(400, "platform staff accounts can't be provisioned", "invalidValue")
            linked = (
                await self.db.execute(
                    select(ScimUser.id).where(
                        ScimUser.organization_id == org.id, ScimUser.user_id == user.id
                    )
                )
            ).first()
            if linked is not None:
                raise ScimError(409, "this account is already provisioned", "uniqueness")
        created_account = user is None
        reclaimed = False
        if user is not None:
            reclaimed = await PlatformAuthService(self.db, self.settings).claim_by_idp(user)
        if user is None:
            user = PlatformUser(
                email=data.email,
                name=_account_name(data),
                password_hash=sec.SSO_ONLY_PASSWORD_HASH,
                email_verified_at=_now(),
                platform_role=PlatformRole.customer,
                default_organization_id=org.id,
            )
            self.db.add(user)
            await self.db.flush()
        su = ScimUser(
            organization_id=org.id,
            user_id=user.id,
            user_name=data.user_name,
            external_id=data.external_id,
            given_name=data.given_name,
            family_name=data.family_name,
            display_name=data.display_name,
            active=data.active,
        )
        self.db.add(su)
        await self.db.flush()
        if data.active:
            await self._join(ctx, su, user)
        if created_account:
            await self.orgs.ensure_personal_org(user)
        await self._audit(
            ctx,
            "scim.user_created",
            user,
            detail={
                "linked_existing_account": not created_account,
                "active": data.active,
                "credentials_reset": reclaimed,
            },
        )
        await self.db.commit()
        return self._user_resource(su, user, [])

    async def replace_user(self, ctx: ScimContext, raw_id: str, body: object) -> dict[str, object]:
        su, user = await self._one_user(ctx, raw_id)
        return await self._apply_user(ctx, su, user, proto.parse_user(body))

    async def patch_user(self, ctx: ScimContext, raw_id: str, body: object) -> dict[str, object]:
        su, user = await self._one_user(ctx, raw_id)
        current = proto.user_patch_base(
            user_name=su.user_name,
            external_id=su.external_id,
            given_name=su.given_name,
            family_name=su.family_name,
            display_name=su.display_name,
            email=user.email,
            active=su.active,
        )
        return await self._apply_user(
            ctx, su, user, proto.parse_user(proto.apply_user_patch(current, body))
        )

    async def _apply_user(
        self, ctx: ScimContext, su: ScimUser, user: PlatformUser, data: proto.UserInput
    ) -> dict[str, object]:
        org = ctx.org
        if data.user_name.lower() != su.user_name.lower() and await self._user_name_taken(
            org.id, data.user_name, except_id=su.id
        ):
            raise ScimError(409, "a user with this userName already exists", "uniqueness")
        if data.email != user.email:
            await self._require_domain(org, data.email)
            if await self._email_is_shared(org, user):
                raise ScimError(
                    409,
                    "this account is used outside this organization, so its e-mail can't be "
                    "changed from here",
                    "mutability",
                )
            taken = (
                await self.db.execute(
                    select(PlatformUser.id).where(PlatformUser.email == data.email)
                )
            ).first()
            if taken is not None:
                raise ScimError(409, "another account already uses this e-mail", "uniqueness")
            await self._audit(ctx, "scim.user_email_changed", user)
            user.email = data.email
        su.user_name = data.user_name
        su.external_id = data.external_id
        su.given_name = data.given_name
        su.family_name = data.family_name
        su.display_name = data.display_name
        su.updated_at = _now()
        name = _account_name(data)
        if name:
            user.name = name
        if data.active and not su.active:
            su.active = True
            await self._join(ctx, su, user)
            await self._audit(ctx, "scim.user_reactivated", user)
        elif not data.active and su.active:
            await self._leave(ctx, user)
            su.active = False
            await self._audit(ctx, "scim.user_deactivated", user)
        else:
            await self._audit(ctx, "scim.user_updated", user)
        await self.db.commit()
        groups = await self._groups_of([su.id])
        return self._user_resource(su, user, groups.get(su.id, []))

    async def delete_user(self, ctx: ScimContext, raw_id: str) -> None:
        """Offboard and forget the SCIM resource. The Builder account itself stays (the person
        may have a personal org); erasing accounts is a separate GDPR flow."""
        su, user = await self._one_user(ctx, raw_id)
        if su.active:
            await self._leave(ctx, user)
        await self.db.delete(su)
        await self._audit(ctx, "scim.user_deleted", user)
        await self.db.commit()

    async def _join(self, ctx: ScimContext, su: ScimUser, user: PlatformUser) -> None:
        """Add the person to the org (a seat), with the role their groups map to."""
        org = ctx.org
        if user.status is not AccountStatus.active:
            raise ScimError(400, "this account is suspended on the platform", "invalidValue")
        if await self.db.get(OrganizationMember, (org.id, user.id)) is not None:
            await self._sync_roles(org, [su.id])
            return
        try:
            await self.orgs.enforce_seat_limit(org.id, extra=1, actor_email=user.email)
        except AppError as exc:
            # enforce_seat_limit already recorded `quota.denied` and rolled back.
            raise ScimError(403, exc.message) from exc
        role = await self._target_role(ctx.directory, su.id) or OrgRole.member
        self.db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role))
        await self.db.flush()
        self.seats_changed = True

    async def _leave(self, ctx: ScimContext, user: PlatformUser) -> None:
        """§4.3 deactivation: this org's access dies, the account and its other orgs stay."""
        org = ctx.org
        member = await self.db.get(OrganizationMember, (org.id, user.id))
        org_projects = select(Project.id).where(Project.organization_id == org.id)
        if member is not None:
            heir = (
                await self.db.execute(
                    select(OrganizationMember.user_id)
                    .where(
                        OrganizationMember.organization_id == org.id,
                        OrganizationMember.role == OrgRole.owner,
                        OrganizationMember.user_id != user.id,
                    )
                    .order_by(OrganizationMember.joined_at)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if member.role is OrgRole.owner and heir is None:
                raise ScimError(
                    409,
                    "this person is the organization's last owner; make someone else an owner "
                    "in Builder first",
                    "mutability",
                )
            if heir is not None:
                await self._hand_over_projects(org, user.id, heir)
            await self.db.execute(
                delete(ProjectMember).where(
                    ProjectMember.user_id == user.id, ProjectMember.project_id.in_(org_projects)
                )
            )
            await self.db.delete(member)
            await self.orgs._reset_default_org(org.id, user.id)  # noqa: SLF001
            self.seats_changed = True
        await self.db.execute(
            update(ApiToken)
            .where(
                ApiToken.user_id == user.id,
                ApiToken.project_id.in_(org_projects),
                ApiToken.revoked_at.is_(None),
            )
            .values(revoked_at=_now())
        )
        await PlatformAuthService(self.db, self.settings).revoke_all_sessions(user)

    async def _email_is_shared(self, org: Organization, user: PlatformUser) -> bool:
        """True when the account matters outside this org: it has a password of its own, or
        belongs to another team org or directory. SCIM must not rename a global identity then."""
        if user.password_hash != sec.SSO_ONLY_PASSWORD_HASH:
            return True
        elsewhere = (
            await self.db.execute(
                select(OrganizationMember.organization_id)
                .join(Organization, Organization.id == OrganizationMember.organization_id)
                .where(
                    OrganizationMember.user_id == user.id,
                    OrganizationMember.organization_id != org.id,
                    Organization.kind != OrgKind.personal,
                )
                .limit(1)
            )
        ).first()
        if elsewhere is not None:
            return True
        other_directory = (
            await self.db.execute(
                select(ScimUser.id)
                .where(ScimUser.user_id == user.id, ScimUser.organization_id != org.id)
                .limit(1)
            )
        ).first()
        return other_directory is not None

    async def _hand_over_projects(
        self, org: Organization, user_id: uuid.UUID, heir: uuid.UUID
    ) -> None:
        owned = (
            (
                await self.db.execute(
                    select(ProjectMember.project_id)
                    .join(Project, Project.id == ProjectMember.project_id)
                    .where(
                        Project.organization_id == org.id,
                        ProjectMember.user_id == user_id,
                        ProjectMember.role == MemberRole.owner,
                    )
                )
            )
            .scalars()
            .all()
        )
        for project_id in owned:
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
            if others:
                continue
            row = await self.db.get(ProjectMember, (project_id, heir))
            if row is None:
                self.db.add(
                    ProjectMember(project_id=project_id, user_id=heir, role=MemberRole.owner)
                )
            else:
                row.role = MemberRole.owner
            await audit_service.record(
                self.db,
                action="scim.project_handed_over",
                via="scim",
                organization_id=org.id,
                project_id=project_id,
                target_type="user",
                target_id=heir,
                detail={"from_user_id": str(user_id)},
            )
        await self.db.flush()

    # == groups -> roles ==========================================================================

    async def _target_role(
        self, directory: ScimDirectory, scim_user_id: uuid.UUID
    ) -> OrgRole | None:
        """None: the dictionary is empty, so groups don't decide roles."""
        mapping = directory.group_roles or {}
        if not mapping:
            return None
        names = (
            (
                await self.db.execute(
                    select(ScimGroup.display_name)
                    .join(ScimGroupMember, ScimGroupMember.group_id == ScimGroup.id)
                    .where(ScimGroupMember.scim_user_id == scim_user_id)
                )
            )
            .scalars()
            .all()
        )
        roles = [OrgRole(mapping[n.lower()]) for n in names if n.lower() in mapping]
        return max(roles, key=lambda r: ORG_ROLE_LEVEL[r]) if roles else OrgRole.member

    async def _sync_roles(self, org: Organization, scim_user_ids: list[uuid.UUID] | None) -> None:
        directory = await self.directory(org.id)
        if directory is None or not directory.group_roles:
            return
        query = select(ScimUser).where(ScimUser.organization_id == org.id, ScimUser.active)
        if scim_user_ids is not None:
            if not scim_user_ids:
                return
            query = query.where(ScimUser.id.in_(scim_user_ids))
        for su in (await self.db.execute(query)).scalars().all():
            member = await self.db.get(OrganizationMember, (org.id, su.user_id))
            role = await self._target_role(directory, su.id)
            if member is None or role is None or member.role is role:
                continue
            if member.role is OrgRole.owner:
                others = (
                    await self.db.execute(
                        select(func.count())
                        .select_from(OrganizationMember)
                        .where(
                            OrganizationMember.organization_id == org.id,
                            OrganizationMember.role == OrgRole.owner,
                            OrganizationMember.user_id != su.user_id,
                        )
                    )
                ).scalar_one()
                if not others:
                    continue  # never leave the org without an owner
            previous = member.role
            member.role = role
            await audit_service.record(
                self.db,
                action="scim.role_changed",
                via="scim",
                organization_id=org.id,
                target_type="user",
                target_id=su.user_id,
                detail={"from": previous.value, "to": role.value},
            )
        await self.db.flush()

    # == groups ===================================================================================

    async def _members_of(
        self, group_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[tuple[str, str]]]:
        out: dict[uuid.UUID, list[tuple[str, str]]] = {gid: [] for gid in group_ids}
        if not group_ids:
            return out
        rows = await self.db.execute(
            select(ScimGroupMember.group_id, ScimUser.id, ScimUser.user_name)
            .join(ScimUser, ScimUser.id == ScimGroupMember.scim_user_id)
            .where(ScimGroupMember.group_id.in_(group_ids))
            .order_by(ScimUser.user_name)
        )
        for gid, uid, name in rows.all():
            out[gid].append((str(uid), name))
        return out

    def _group_resource(
        self, g: ScimGroup, members: list[tuple[str, str]] | None
    ) -> dict[str, object]:
        return proto.group_resource(
            base_url=self.base_url(),
            id=str(g.id),
            display_name=g.display_name,
            external_id=g.external_id,
            members=members,
            created=_iso(g.created_at),
            last_modified=_iso(g.updated_at),
        )

    async def list_groups(
        self,
        ctx: ScimContext,
        filter_text: str | None,
        start: int,
        count: int,
        *,
        with_members: bool = True,
    ) -> dict[str, object]:
        conditions: list[object] = [ScimGroup.organization_id == ctx.org.id]
        if filter_text:
            f = proto.parse_filter(filter_text, proto.GROUP_FILTER_ATTRS)
            if f.attr == "displayname":
                conditions.append(func.lower(ScimGroup.display_name) == f.value.lower())
            elif f.attr == "externalid":
                conditions.append(ScimGroup.external_id == f.value)
            else:
                gid = _uuid(f.value)
                if gid is None:
                    return proto.list_response([], total=0, start_index=start)
                conditions.append(ScimGroup.id == gid)
        base = select(ScimGroup).where(*conditions)  # type: ignore[arg-type]
        total = (
            await self.db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        groups = (
            (
                await self.db.execute(
                    base.order_by(ScimGroup.created_at, ScimGroup.id).offset(start - 1).limit(count)
                )
            )
            .scalars()
            .all()
        )
        members = await self._members_of([g.id for g in groups]) if with_members else {}
        return proto.list_response(
            [self._group_resource(g, members.get(g.id) if with_members else None) for g in groups],
            total=int(total),
            start_index=start,
        )

    async def _one_group(self, ctx: ScimContext, raw_id: str) -> ScimGroup:
        gid = _uuid(raw_id)
        group = await self.db.get(ScimGroup, gid) if gid is not None else None
        if group is None or group.organization_id != ctx.org.id:
            raise _not_found("group")
        return group

    async def get_group(
        self, ctx: ScimContext, raw_id: str, *, with_members: bool = True
    ) -> dict[str, object]:
        group = await self._one_group(ctx, raw_id)
        members = (await self._members_of([group.id]))[group.id] if with_members else None
        return self._group_resource(group, members)

    async def _name_taken(self, org_id: uuid.UUID, name: str, except_id: uuid.UUID | None) -> bool:
        conditions = [
            ScimGroup.organization_id == org_id,
            func.lower(ScimGroup.display_name) == name.lower(),
        ]
        if except_id is not None:
            conditions.append(ScimGroup.id != except_id)
        return (await self.db.execute(select(ScimGroup.id).where(*conditions))).first() is not None

    async def _own_user_ids(self, org_id: uuid.UUID, raw: list[str]) -> set[uuid.UUID]:
        """Member ids that are this org's SCIM users; anything else is ignored (never another
        org's users)."""
        ids = {i for i in (_uuid(r) for r in raw) if i is not None}
        if not ids:
            return set()
        rows = await self.db.execute(
            select(ScimUser.id).where(ScimUser.organization_id == org_id, ScimUser.id.in_(ids))
        )
        return set(rows.scalars())

    async def _set_members(self, group: ScimGroup, wanted: set[uuid.UUID]) -> set[uuid.UUID]:
        current = set(
            (
                await self.db.execute(
                    select(ScimGroupMember.scim_user_id).where(ScimGroupMember.group_id == group.id)
                )
            ).scalars()
        )
        for uid in wanted - current:
            self.db.add(ScimGroupMember(group_id=group.id, scim_user_id=uid))
        gone = current - wanted
        if gone:
            await self.db.execute(
                delete(ScimGroupMember).where(
                    ScimGroupMember.group_id == group.id, ScimGroupMember.scim_user_id.in_(gone)
                )
            )
        await self.db.flush()
        return current ^ wanted

    async def create_group(self, ctx: ScimContext, body: object) -> dict[str, object]:
        data = proto.parse_group(body)
        if await self._name_taken(ctx.org.id, data.display_name, None):
            raise ScimError(409, "a group with this displayName already exists", "uniqueness")
        group = ScimGroup(
            organization_id=ctx.org.id, display_name=data.display_name, external_id=data.external_id
        )
        self.db.add(group)
        await self.db.flush()
        changed = await self._set_members(
            group, await self._own_user_ids(ctx.org.id, data.member_ids)
        )
        await self._sync_roles(ctx.org, list(changed))
        await self._audit_group(ctx, "scim.group_created", group)
        await self.db.commit()
        return self._group_resource(group, (await self._members_of([group.id]))[group.id])

    async def replace_group(self, ctx: ScimContext, raw_id: str, body: object) -> dict[str, object]:
        group = await self._one_group(ctx, raw_id)
        data = proto.parse_group(body)
        if await self._name_taken(ctx.org.id, data.display_name, group.id):
            raise ScimError(409, "a group with this displayName already exists", "uniqueness")
        group.display_name = data.display_name
        group.external_id = data.external_id
        group.updated_at = _now()
        changed = await self._set_members(
            group, await self._own_user_ids(ctx.org.id, data.member_ids)
        )
        await self._after_group_change(ctx, group, changed)
        return self._group_resource(group, (await self._members_of([group.id]))[group.id])

    async def patch_group(self, ctx: ScimContext, raw_id: str, body: object) -> dict[str, object]:
        group = await self._one_group(ctx, raw_id)
        gp = proto.parse_group_patch(body)
        if gp.display_name is not None and gp.display_name != group.display_name:
            if await self._name_taken(ctx.org.id, gp.display_name, group.id):
                raise ScimError(409, "a group with this displayName already exists", "uniqueness")
            group.display_name = gp.display_name
        if gp.external_id_set:
            group.external_id = gp.external_id
        current = set(
            (
                await self.db.execute(
                    select(ScimGroupMember.scim_user_id).where(ScimGroupMember.group_id == group.id)
                )
            ).scalars()
        )
        wanted = (
            await self._own_user_ids(ctx.org.id, gp.replace) if gp.replace is not None else current
        )
        wanted |= await self._own_user_ids(ctx.org.id, gp.add)
        wanted -= {i for i in (_uuid(r) for r in gp.remove) if i is not None}
        group.updated_at = _now()
        changed = await self._set_members(group, wanted)
        # A rename can move a group into or out of the dictionary: re-check all its members.
        await self._after_group_change(ctx, group, changed | wanted | current)
        return self._group_resource(group, (await self._members_of([group.id]))[group.id])

    async def _after_group_change(
        self, ctx: ScimContext, group: ScimGroup, affected: set[uuid.UUID]
    ) -> None:
        await self._sync_roles(ctx.org, list(affected))
        await self._audit_group(ctx, "scim.group_updated", group)
        await self.db.commit()

    async def delete_group(self, ctx: ScimContext, raw_id: str) -> None:
        group = await self._one_group(ctx, raw_id)
        members = list(
            (
                await self.db.execute(
                    select(ScimGroupMember.scim_user_id).where(ScimGroupMember.group_id == group.id)
                )
            ).scalars()
        )
        await self.db.delete(group)
        await self.db.flush()
        await self._sync_roles(ctx.org, members)
        await self._audit_group(ctx, "scim.group_deleted", group)
        await self.db.commit()

    # == audit ====================================================================================

    async def _audit(
        self,
        ctx: ScimContext,
        action: str,
        user: PlatformUser,
        *,
        result: AuditResult = AuditResult.ok,
        detail: dict[str, object] | None = None,
    ) -> None:
        await audit_service.record(
            self.db,
            action=action,
            result=result,
            via="scim",
            organization_id=ctx.org.id,
            target_type="user",
            target_id=user.id,
            client_ip=ctx.info.client_ip,
            request_id=ctx.info.request_id,
            detail=detail,
        )

    async def _audit_group(self, ctx: ScimContext, action: str, group: ScimGroup) -> None:
        await audit_service.record(
            self.db,
            action=action,
            via="scim",
            organization_id=ctx.org.id,
            target_type="scim_group",
            target_id=group.id,
            client_ip=ctx.info.client_ip,
            request_id=ctx.info.request_id,
            detail={"display_name": group.display_name},
        )


def _account_name(data: proto.UserInput) -> str:
    full = " ".join(x for x in (data.given_name, data.family_name) if x)
    return (data.display_name or full or data.email.split("@", 1)[0])[:100]


def normalize_group_roles(raw: dict[str, str]) -> dict[str, str]:
    """Group names compare case-insensitively; roles must be org roles."""
    out: dict[str, str] = {}
    if len(raw) > 100:
        raise AppError(
            code="validation_error", message="at most 100 group mappings", status_code=422
        )
    for name, role in raw.items():
        key = name.strip().lower()
        if not key or len(key) > 255:
            raise AppError(
                code="validation_error",
                message="group names must be 1–255 characters",
                status_code=422,
            )
        if role not in {r.value for r in OrgRole}:
            raise AppError(
                code="validation_error", message=f"unknown role '{role}'", status_code=422
            )
        out[key] = role
    return out


__all__ = ["ScimContext", "ScimService", "new_token", "normalize_group_roles"]
