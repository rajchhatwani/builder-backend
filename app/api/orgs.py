"""Customer-facing organizations API (PLATFORM_SAAS_PLAN §8).

Routes:
    GET    /orgs                                      the signed-in user's orgs
    POST   /orgs                                      create a team org
    GET    /orgs/invitations/pending                  the signed-in user's open invites
    POST   /orgs/invitations/accept                   accept an invite by token (the link)
    POST   /orgs/invitations/{id}/accept              accept one of my pending invites
    GET    /orgs/{slug}                               one org
    PATCH  /orgs/{slug}                               rename
    DELETE /orgs/{slug}                               request deletion (locks; grace period)
    POST   /orgs/{slug}/deletion/cancel               revoke the request (unlocks)
    GET    /orgs/{slug}/members                       members
    PATCH  /orgs/{slug}/members/{user_id}             change role
    DELETE /orgs/{slug}/members/{user_id}             remove a member, or leave
    POST   /orgs/{slug}/transfer                      transfer ownership
    GET    /orgs/{slug}/invitations                   invites
    POST   /orgs/{slug}/invitations                   invite (e-mailed when SMTP is set up)
    POST   /orgs/{slug}/invitations/{id}/resend       new link, new expiry, e-mailed again
    DELETE /orgs/{slug}/invitations/{id}              revoke
    GET    /orgs/{slug}/projects                      projects (members: only their own)
    POST   /orgs/{slug}/projects/{project_id}/join    an admin adds themselves to a project
    POST   /orgs/{slug}/projects/{project_id}/transfer  move a project to another owned org
    GET    /orgs/{slug}/plan                          plan + usage
    POST   /orgs/{slug}/billing/checkout              start a Stripe Checkout
    POST   /orgs/{slug}/billing/portal                open the Stripe Billing Portal
    GET    /orgs/{slug}/audit                         the org's slice of the audit log
    GET    /orgs/{slug}/export                        every record of the org as one JSON file
                                                      (owner, session only; works while locked)
    GET    /orgs/{slug}/policies                      security policies (§8)
    PATCH  /orgs/{slug}/policies                      require MFA, session TTL (session only)

Every /orgs/{slug} route resolves the org and checks the caller's role through `org_context`,
from the flat table `platform_authz.ORG_ROUTE_ROLES` (§5). Handlers only add the rules a flat
table can't express (owners are made and unmade by owners; anyone may leave).
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination, pagination
from app.api.security import (
    OrgContext,
    current_principal,
    forbidden,
    not_found,
    org_context,
    require_write_scope,
)
from app.config import Settings, get_settings
from app.core import platform_authz as authz
from app.core import rls
from app.db import get_session
from app.exceptions import AppError
from app.models.enums import OrgRole
from app.models.platform import (
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    PlatformUser,
)
from app.schemas.common import Page
from app.schemas.organization import (
    CheckoutCreate,
    CheckoutRead,
    InvitationAccept,
    InvitationCreate,
    InvitationCreated,
    InvitationRead,
    OrganizationCreate,
    OrganizationMemberRead,
    OrganizationMemberUpdate,
    OrganizationRead,
    OrganizationUpdate,
    OrgAuditRead,
    OrgPlanRead,
    OrgPoliciesRead,
    OrgPoliciesUpdate,
    OrgProjectJoin,
    OrgUsage,
    PlanRead,
    PortalRead,
    ProjectTransfer,
    SubscriptionRead,
)
from app.schemas.project import ProjectRead
from app.services import audit_service, mail_service
from app.services.access_service import Principal
from app.services.billing_service import BillingService, checkout_available, portal_available
from app.services.impersonation_service import ImpersonationService
from app.services.org_export_service import OrgExportService
from app.services.organization_service import OrganizationService, OrgSummary

router = APIRouter(prefix="/orgs", tags=["organizations"])

SLUG = Path(min_length=1, max_length=100)
USER_ID = Path()
INVITATION_ID = Path()
PROJECT_ID = Path()
ACTION_PREFIX = Query(default=None, max_length=64)


def _org_read(summary: OrgSummary) -> OrganizationRead:
    org = summary.organization
    return OrganizationRead(
        id=org.id,
        name=org.name,
        slug=org.slug,
        kind=org.kind,
        created_at=org.created_at,
        my_role=summary.role,
        member_count=summary.member_count,
        deletion_requested_at=org.deletion_requested_at,
        deletion_scheduled_for=org.deletion_scheduled_for,
        require_mfa=org.require_mfa,
        session_ttl_hours=org.session_ttl_hours,
    )


def _invitation_read(inv: OrganizationInvitation, slug: str, name: str) -> InvitationRead:
    return InvitationRead(
        id=inv.id,
        organization_id=inv.organization_id,
        organization_slug=slug,
        organization_name=name,
        email=inv.email,
        role=inv.role,
        status=OrganizationService._invitation_status(inv),  # noqa: SLF001
        created_at=inv.created_at,
        expires_at=inv.expires_at,
    )


def _invite_url(raw_token: str) -> str:
    return f"{get_settings().public_app_url.rstrip('/')}/#/invite/{raw_token}"


async def _audit(
    db: AsyncSession,
    ctx: OrgContext,
    action: str,
    *,
    target_type: str = "organization",
    target_id: object = None,
    project_id: uuid.UUID | None = None,
    detail: dict[str, object] | None = None,
) -> None:
    await audit_service.record(
        db,
        action=action,
        actor_id=ctx.principal.user.id,
        actor_email=ctx.principal.user.email,
        via=ctx.principal.via,
        organization_id=ctx.org.id,
        project_id=project_id,
        target_type=target_type,
        target_id=target_id if target_id is not None else ctx.org.id,  # type: ignore[arg-type]
        detail=detail,
    )


# -- my orgs ---------------------------------------------------------------------------


@router.get("", response_model=Page[OrganizationRead])
async def list_my_orgs(
    page: Pagination = Depends(pagination),
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> Page[OrganizationRead]:
    summaries = await OrganizationService(db).list_for_user(principal.user.id)
    if principal.impersonation is not None:  # §4.5: a "view as" session sees its one org only
        summaries = [
            s for s in summaries if s.organization.id == principal.impersonation.organization_id
        ]
    items = [_org_read(s) for s in summaries[page.offset : page.offset + page.limit]]
    return Page[OrganizationRead](
        items=items, total=len(summaries), limit=page.limit, offset=page.offset
    )


@router.post("", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
async def create_org(
    body: OrganizationCreate,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> OrganizationRead:
    require_write_scope(principal)
    org = await OrganizationService(db).create_team_org(
        principal.user, name=body.name, slug=body.slug
    )
    await audit_service.record(
        db,
        action="org.created",
        actor_id=principal.user.id,
        actor_email=principal.user.email,
        organization_id=org.id,
        target_type="organization",
        target_id=org.id,
        detail={"slug": org.slug},
    )
    await db.commit()
    return _org_read(OrgSummary(organization=org, role=OrgRole.owner, member_count=1))


# -- my invitations (bare /orgs/invitations/… must come BEFORE /orgs/{slug}) -------------


@router.get("/invitations/pending", response_model=Page[InvitationRead])
async def list_my_pending_invitations(
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> Page[InvitationRead]:
    if principal.user.email_verified_at is None:
        return Page[InvitationRead](items=[], total=0, limit=0, offset=0)
    rows = await OrganizationService(db).list_pending_for_email(principal.user.email)
    items = [_invitation_read(r.invitation, r.organization.slug, r.organization.name) for r in rows]
    return Page[InvitationRead](items=items, total=len(items), limit=len(items), offset=0)


async def _accepted(
    db: AsyncSession,
    principal: Principal,
    service: OrganizationService,
    org: Organization,
    role: OrgRole,
) -> OrganizationRead:
    count = len(await service.list_members(org.id))
    await audit_service.record(
        db,
        action="org.invitation_accepted",
        actor_id=principal.user.id,
        actor_email=principal.user.email,
        organization_id=org.id,
        target_type="organization",
        target_id=org.id,
    )
    await db.commit()
    # C.4: a new member may raise the billed seat count. After the commit, best effort.
    await BillingService(db).sync_seats(org.id)
    return _org_read(OrgSummary(organization=org, role=role, member_count=count))


@router.post("/invitations/accept", response_model=OrganizationRead)
async def accept_invitation(
    body: InvitationAccept,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> OrganizationRead:
    service = OrganizationService(db)
    require_write_scope(principal)
    org, role = await service.accept_invitation(principal.user, body.token)
    return await _accepted(db, principal, service, org, role)


@router.post("/invitations/{invitation_id}/accept", response_model=OrganizationRead)
async def accept_invitation_by_id(
    invitation_id: uuid.UUID,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> OrganizationRead:
    require_write_scope(principal)
    service = OrganizationService(db)
    org, role = await service.accept_invitation_by_id(principal.user, invitation_id)
    return await _accepted(db, principal, service, org, role)


# -- one org ----------------------------------------------------------------------------


@router.get("/{slug}", response_model=OrganizationRead)
async def get_org(slug: str = SLUG, ctx: OrgContext = Depends(org_context)) -> OrganizationRead:
    return _org_read(ctx.summary)


@router.patch("/{slug}", response_model=OrganizationRead)
async def rename_org(
    body: OrganizationUpdate,
    slug: str = SLUG,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
) -> OrganizationRead:
    if body.name is not None and body.name.strip() != ctx.org.name:
        old = ctx.org.name
        await OrganizationService(db).rename(ctx.org.id, body.name)
        await _audit(db, ctx, "org.renamed", detail={"from": old, "to": body.name.strip()})
        await db.commit()
    return _org_read(ctx.summary)


@router.delete("/{slug}", response_model=OrganizationRead, status_code=status.HTTP_202_ACCEPTED)
async def request_org_deletion(
    slug: str = SLUG,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
) -> OrganizationRead:
    """Request deletion: the org is locked now and deleted when the grace period ends
    (`BUILDER_ORG_DELETION_GRACE_DAYS`, default 7). An owner can revoke it until then."""
    org = await OrganizationService(db).request_deletion(
        ctx.org.id,
        actor_id=ctx.principal.user.id,
        grace_days=get_settings().org_deletion_grace_days,
    )
    scheduled = org.deletion_scheduled_for.isoformat() if org.deletion_scheduled_for else None
    await _audit(db, ctx, "org.deletion_requested", detail={"scheduled_for": scheduled})
    await db.commit()
    return _org_read(ctx.summary)


@router.post("/{slug}/deletion/cancel", response_model=OrganizationRead)
async def cancel_org_deletion(
    slug: str = SLUG,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
) -> OrganizationRead:
    await OrganizationService(db).cancel_deletion(ctx.org.id)
    await _audit(db, ctx, "org.deletion_canceled")
    await db.commit()
    return _org_read(ctx.summary)


# -- members ----------------------------------------------------------------------------


@router.get(
    "/{slug}/members",
    response_model=Page[OrganizationMemberRead],
    response_model_exclude_unset=True,
)
async def list_members(
    slug: str = SLUG,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
) -> Page[OrganizationMemberRead]:
    rows = await OrganizationService(db).list_members(ctx.org.id)
    # §8: the People columns for last sign-in and 2FA belong to admins (and to each person's
    # own row). For a plain member they are left out of the response, not sent as false/null.
    see_all = authz.org_role_allows(ctx.role, OrgRole.admin)

    def private(u: PlatformUser) -> dict[str, Any]:
        return {"last_login_at": u.last_login_at, "mfa_enabled": u.mfa_enabled}

    items = [
        OrganizationMemberRead(
            user_id=u.id,
            email=u.email,
            name=u.name,
            role=m.role,
            joined_at=m.joined_at,
            status=u.status,
            **(private(u) if see_all or u.id == ctx.principal.user.id else {}),
        )
        for m, u in rows
    ]
    return Page[OrganizationMemberRead](items=items, total=len(items), limit=len(items), offset=0)


@router.patch("/{slug}/members/{user_id}", response_model=OrganizationMemberRead)
async def update_member_role(
    body: OrganizationMemberUpdate,
    slug: str = SLUG,
    user_id: uuid.UUID = USER_ID,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
) -> OrganizationMemberRead:
    service = OrganizationService(db)
    member = await service.set_member_role(ctx.org.id, user_id, body.role, actor_role=ctx.role)
    rows = await service.list_members(ctx.org.id)
    user = next((u for m, u in rows if m.user_id == user_id), None)
    if user is None:
        raise not_found()
    await _audit(
        db,
        ctx,
        "org.member_role_changed",
        target_type="user",
        target_id=user_id,
        detail={"new_role": member.role.value},
    )
    await db.commit()
    return OrganizationMemberRead(
        user_id=user.id,
        email=user.email,
        name=user.name,
        role=member.role,
        joined_at=member.joined_at,
        status=user.status,
        last_login_at=user.last_login_at,
        mfa_enabled=user.mfa_enabled,
    )


@router.delete("/{slug}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    slug: str = SLUG,
    user_id: uuid.UUID = USER_ID,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
) -> None:
    service = OrganizationService(db)
    leaving = user_id == ctx.principal.user.id
    if not leaving:  # anyone may leave; removing someone else is an admin's job
        ctx.require(OrgRole.admin, await service.owner_emails(ctx.org.id))
    await service.remove_member(
        ctx.org.id, user_id, actor_id=ctx.principal.user.id, actor_role=ctx.role
    )
    await _audit(
        db,
        ctx,
        "org.member_left" if leaving else "org.member_removed",
        target_type="user",
        target_id=user_id,
    )
    await db.commit()
    await BillingService(db).sync_seats(ctx.org.id)


@router.post("/{slug}/transfer", status_code=status.HTTP_204_NO_CONTENT)
async def transfer_ownership(
    to_user_id: uuid.UUID,
    slug: str = SLUG,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
) -> None:
    await OrganizationService(db).transfer_ownership(ctx.org.id, ctx.principal.user.id, to_user_id)
    await _audit(db, ctx, "org.ownership_transferred", target_type="user", target_id=to_user_id)
    await db.commit()


# -- invitations ------------------------------------------------------------------------


@router.get("/{slug}/invitations", response_model=Page[InvitationRead])
async def list_invitations(
    slug: str = SLUG,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
) -> Page[InvitationRead]:
    rows = await OrganizationService(db).list_invitations(ctx.org.id)
    items = [_invitation_read(inv, ctx.org.slug, ctx.org.name) for inv in rows]
    return Page[InvitationRead](items=items, total=len(items), limit=len(items), offset=0)


async def _created(
    ctx: OrgContext, invitation: OrganizationInvitation, raw: str
) -> InvitationCreated:
    url = _invite_url(raw)
    emailed = await mail_service.send_invitation(
        to=invitation.email,
        org_name=ctx.org.name,
        inviter=ctx.principal.user.name or ctx.principal.user.email,
        url=url,
    )
    base = _invitation_read(invitation, ctx.org.slug, ctx.org.name)
    return InvitationCreated(**base.model_dump(), token=raw, invite_url=url, emailed=emailed)


@router.post(
    "/{slug}/invitations", response_model=InvitationCreated, status_code=status.HTTP_201_CREATED
)
async def create_invitation(
    body: InvitationCreate,
    slug: str = SLUG,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
) -> InvitationCreated:
    service = OrganizationService(db)
    if body.role is OrgRole.owner:  # owners are made by owners (§2.2)
        ctx.require(OrgRole.owner, await service.owner_emails(ctx.org.id))
    invitation, raw = await service.create_invitation(
        ctx.org.id, email=body.email, role=body.role, invited_by=ctx.principal.user.id
    )
    await _audit(
        db,
        ctx,
        "org.invitation_created",
        detail={"email": invitation.email, "role": invitation.role.value},
    )
    await db.commit()
    return await _created(ctx, invitation, raw)


@router.post("/{slug}/invitations/{invitation_id}/resend", response_model=InvitationCreated)
async def resend_invitation(
    slug: str = SLUG,
    invitation_id: uuid.UUID = INVITATION_ID,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
) -> InvitationCreated:
    service = OrganizationService(db)
    existing = await db.get(OrganizationInvitation, invitation_id)
    if existing is not None and existing.role is OrgRole.owner:
        ctx.require(OrgRole.owner, await service.owner_emails(ctx.org.id))
    invitation, raw = await service.resend_invitation(
        ctx.org.id, invitation_id, actor_id=ctx.principal.user.id
    )
    await _audit(
        db, ctx, "org.invitation_resent", target_type="invitation", target_id=invitation_id
    )
    await db.commit()
    return await _created(ctx, invitation, raw)


@router.delete("/{slug}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    slug: str = SLUG,
    invitation_id: uuid.UUID = INVITATION_ID,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
) -> None:
    await OrganizationService(db).revoke_invitation(ctx.org.id, invitation_id)
    await _audit(
        db, ctx, "org.invitation_revoked", target_type="invitation", target_id=invitation_id
    )
    await db.commit()


# -- projects ---------------------------------------------------------------------------


@router.get("/{slug}/projects", response_model=Page[ProjectRead])
async def list_org_projects(
    slug: str = SLUG,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
) -> Page[ProjectRead]:
    # §8: members see the org's projects they're on; admins and owners see all of them.
    only = None if ctx.role in (OrgRole.admin, OrgRole.owner) else ctx.principal.user.id
    projects = await OrganizationService(db).list_projects(ctx.org.id, only_for_user=only)
    items = [ProjectRead.model_validate(p) for p in projects]
    return Page[ProjectRead](items=items, total=len(items), limit=len(items), offset=0)


@router.post("/{slug}/projects/{project_id}/join", status_code=status.HTTP_201_CREATED)
async def join_org_project(
    body: OrgProjectJoin,
    slug: str = SLUG,
    project_id: uuid.UUID = PROJECT_ID,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    member = await OrganizationService(db).join_project(
        ctx.org.id, project_id, ctx.principal.user.id, body.role
    )
    await _audit(
        db,
        ctx,
        "org.project_joined",
        target_type="project",
        target_id=project_id,
        project_id=project_id,
        detail={"role": member.role.value},
    )
    await db.commit()
    return {"project_id": str(project_id), "role": member.role.value}


@router.post("/{slug}/projects/{project_id}/transfer", response_model=ProjectRead)
async def transfer_org_project(
    body: ProjectTransfer,
    slug: str = SLUG,
    project_id: uuid.UUID = PROJECT_ID,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
) -> ProjectRead:
    from_org_id = ctx.org.id
    # The one org-scoped action that reads a second org: lift the RLS confinement (§3.3). The
    # caller was authorised for the source org above, and the service re-checks the destination.
    await rls.release(db)
    project, to_org = await OrganizationService(db).transfer_project(
        project_id, from_org_id=from_org_id, to_slug=body.to_slug, actor=ctx.principal.user
    )
    for org_id in (from_org_id, to_org.id):  # both orgs' audit logs show the move
        await audit_service.record(
            db,
            action="org.project_transferred",
            actor_id=ctx.principal.user.id,
            actor_email=ctx.principal.user.email,
            organization_id=org_id,
            project_id=project_id,
            target_type="project",
            target_id=project_id,
            detail={"from": str(from_org_id), "to": str(to_org.id)},
        )
    await db.commit()
    return ProjectRead.model_validate(project)


# -- plan and billing -------------------------------------------------------------------


@router.get("/{slug}/plan", response_model=OrgPlanRead)
async def get_org_plan(
    slug: str = SLUG,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
) -> OrgPlanRead:
    service = OrganizationService(db)
    _plan, sub = await service.plan_and_subscription(ctx.org.id)
    if await service.expire_trial_if_due(sub):
        await db.commit()
    plan, sub = await service.plan_and_subscription(ctx.org.id)
    usage = await service.usage(ctx.org.id, viewer_id=ctx.principal.user.id)
    return OrgPlanRead(
        plan=PlanRead.model_validate(plan),
        subscription=SubscriptionRead.model_validate(sub),
        usage=OrgUsage.model_validate(usage),
        checkout_available=checkout_available(),
        upgrades=[
            PlanRead.model_validate(p) for p in await BillingService(db).upgrade_options(plan.id)
        ],
        portal_available=portal_available(sub),
    )


@router.post(
    "/{slug}/billing/checkout", response_model=CheckoutRead, status_code=status.HTTP_201_CREATED
)
async def start_checkout(
    body: CheckoutCreate,
    slug: str = SLUG,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
) -> CheckoutRead:
    session = await BillingService(db).start_checkout(
        ctx.org, plan_id=body.plan_id, actor=ctx.principal.user
    )
    return CheckoutRead(id=session.id, url=session.url)


@router.post(
    "/{slug}/billing/portal", response_model=PortalRead, status_code=status.HTTP_201_CREATED
)
async def open_billing_portal(
    slug: str = SLUG,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
) -> PortalRead:
    """Stripe Billing Portal for a paying org: change plan, update the card, cancel. The
    resulting changes reach the platform through the webhook, not through this call."""
    url = await BillingService(db).start_portal(ctx.org, actor=ctx.principal.user)
    return PortalRead(url=url)


# -- audit (§8: org-scoped, unconditional organization_id filter) -------------------------


@router.get("/{slug}/audit", response_model=Page[OrgAuditRead])
async def org_audit(
    slug: str = SLUG,
    page: Pagination = Depends(pagination),
    action: str | None = ACTION_PREFIX,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
) -> Page[OrgAuditRead]:
    rows, total = await audit_service.search(
        db, limit=page.limit, offset=page.offset, action=action, organization_id=ctx.org.id
    )
    return Page[OrgAuditRead](
        items=[OrgAuditRead.model_validate(r) for r in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


# -- data export (§9, §11) ------------------------------------------------------------------


@router.get("/{slug}/export")
async def export_org(
    slug: str = SLUG,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """The org's records as one downloadable JSON file: people, projects with their specs,
    policies, plan and the org's audit trail. Owners only, from a signed-in session; no
    credentials, hashes or customer secrets are in it (see OrgExportService)."""
    document = await OrgExportService(db).build(ctx.org)
    await _audit(
        db,
        ctx,
        "org.exported",
        detail={
            "members": len(document["members"]),
            "projects": len(document["projects"]),
            "audit_entries": len(document["audit"]),
        },
    )
    await db.commit()
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return Response(
        content=json.dumps(document, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{ctx.org.slug}-export-{stamp}.json"',
            "Cache-Control": "no-store",
        },
    )


# -- security policies (§8, §4.4, §12.D.7) -------------------------------------------------


async def _policies_read(
    db: AsyncSession, org: Organization, settings: Settings
) -> OrgPoliciesRead:
    without = (
        await db.execute(
            select(func.count())
            .select_from(OrganizationMember)
            .join(PlatformUser, PlatformUser.id == OrganizationMember.user_id)
            .where(
                OrganizationMember.organization_id == org.id,
                PlatformUser.totp_enabled_at.is_(None),
            )
        )
    ).scalar_one()
    return OrgPoliciesRead(
        require_mfa=org.require_mfa,
        session_ttl_hours=org.session_ttl_hours,
        members_without_mfa=int(without),
        default_session_hours=settings.refresh_token_days * 24,
        allow_impersonation=org.allow_impersonation,
    )


@router.get("/{slug}/policies", response_model=OrgPoliciesRead)
async def get_policies(
    slug: str = SLUG,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> OrgPoliciesRead:
    return await _policies_read(db, ctx.org, settings)


@router.patch("/{slug}/policies", response_model=OrgPoliciesRead)
async def update_policies(
    body: OrgPoliciesUpdate,
    slug: str = SLUG,
    ctx: OrgContext = Depends(org_context),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> OrgPoliciesRead:
    """Require MFA for every member, and/or cap how long a sign-in lasts. Turning MFA on needs
    the admin's own session to have used MFA, so nobody locks themselves out."""
    if ctx.principal.via != "session":
        raise forbidden("security policies need a signed-in session", "session_required")
    org = ctx.org
    changed: dict[str, object] = {}
    sent = body.model_fields_set
    if "require_mfa" in sent and body.require_mfa is not None:
        if body.require_mfa and not org.require_mfa and not ctx.principal.mfa_satisfied:
            raise AppError(
                code="enable_mfa_first",
                message=(
                    "turn on two-factor authentication for your own account and sign in with "
                    "it before requiring it for everyone"
                ),
                status_code=409,
            )
        if body.require_mfa != org.require_mfa:
            org.require_mfa = body.require_mfa
            changed["require_mfa"] = body.require_mfa
    if "session_ttl_hours" in sent and body.session_ttl_hours != org.session_ttl_hours:
        org.session_ttl_hours = body.session_ttl_hours
        changed["session_ttl_hours"] = body.session_ttl_hours
    if (
        "allow_impersonation" in sent
        and body.allow_impersonation is not None
        and body.allow_impersonation != org.allow_impersonation
    ):
        org.allow_impersonation = body.allow_impersonation
        changed["allow_impersonation"] = body.allow_impersonation
        if not body.allow_impersonation:
            # Consent withdrawn: any "view as" session of this org ends now, and says why.
            await ImpersonationService(db, settings).end_all_for_org(
                org.id, by=ctx.principal.user, why="consent_withdrawn"
            )
    if changed:
        await _audit(db, ctx, "org.policy_changed", detail=changed)
        await db.commit()
    return await _policies_read(db, org, settings)
