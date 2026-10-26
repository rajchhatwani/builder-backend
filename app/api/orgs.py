"""Customer-facing organizations API — Phase A.

Routes:
    GET    /orgs                            list the signed-in user's orgs
    POST   /orgs                            create a team org
    GET    /orgs/{slug}                     one org (member-only)
    GET    /orgs/{slug}/members             list members (member-only)
    PATCH  /orgs/{slug}/members/{user_id}   change role (admin/owner only)
    DELETE /orgs/{slug}/members/{user_id}   remove member (admin/owner only)
    POST   /orgs/{slug}/transfer            transfer ownership (owner only)
    DELETE /orgs/{slug}                     soft-delete a team org (owner only)
    GET    /orgs/{slug}/invitations         list invites (admin/owner only)
    POST   /orgs/{slug}/invitations         create invite (admin/owner only)
    DELETE /orgs/{slug}/invitations/{id}    revoke invite (admin/owner only)
    GET    /orgs/invitations/pending        the signed-in user's open invites
    POST   /orgs/invitations/accept         accept an invite by token
    GET    /orgs/{slug}/projects            list the org's projects
    GET    /orgs/{slug}/plan                plan + usage
    POST   /orgs/{slug}/billing/checkout    start a Stripe Checkout (admin/owner only)
"""

import uuid

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination, pagination
from app.api.security import current_principal, forbidden, not_found, request_info
from app.db import get_session
from app.exceptions import AppError
from app.models.enums import OrgRole
from app.schemas.common import Page
from app.schemas.organization import (
    CheckoutCreate,
    CheckoutRead,
    PortalRead,
    InvitationAccept,
    InvitationCreate,
    InvitationCreated,
    InvitationRead,
    OrganizationCreate,
    OrganizationMemberRead,
    OrganizationMemberUpdate,
    OrganizationRead,
    OrgPlanRead,
    OrgUsage,
    PlanRead,
    SubscriptionRead,
)
from app.schemas.project import ProjectRead
from app.services import audit_service
from app.services.access_service import Principal
from app.services.billing_service import (
    BillingService,
    checkout_available,
    portal_available,
)
from app.services.organization_service import OrgSummary, OrganizationService

router = APIRouter(prefix="/orgs", tags=["organizations"])

ORG_ROLE_LEVEL = {OrgRole.member: 1, OrgRole.admin: 2, OrgRole.owner: 3}


def _require_role(summary: OrgSummary, needed: OrgRole) -> None:
    if ORG_ROLE_LEVEL[summary.role] < ORG_ROLE_LEVEL[needed]:
        raise forbidden(
            f"this needs the organization role '{needed.value}'", "org_role_required"
        )


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
    )


# -- my orgs ---------------------------------------------------------------------------


@router.get("", response_model=Page[OrganizationRead])
async def list_my_orgs(
    page: Pagination = Depends(pagination),
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> Page[OrganizationRead]:
    summaries = await OrganizationService(db).list_for_user(principal.user.id)
    total = len(summaries)
    items = [
        _org_read(s) for s in summaries[page.offset : page.offset + page.limit]
    ]
    return Page[OrganizationRead](items=items, total=total, limit=page.limit, offset=page.offset)


@router.post("", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
async def create_org(
    body: OrganizationCreate,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> OrganizationRead:
    service = OrganizationService(db)
    org = await service.create_team_org(
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


# -- pending invitations list (bare /orgs/invitations/…) comes BEFORE /orgs/{slug} ----


@router.get("/invitations/pending", response_model=Page[InvitationRead])
async def list_my_pending_invitations(
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> Page[InvitationRead]:
    rows = await OrganizationService(db).list_pending_for_email(principal.user.email)
    items = [
        InvitationRead(
            id=r.invitation.id,
            organization_id=r.invitation.organization_id,
            organization_slug=r.organization.slug,
            organization_name=r.organization.name,
            email=r.invitation.email,
            role=r.invitation.role,
            status=r.status,
            created_at=r.invitation.created_at,
            expires_at=r.invitation.expires_at,
        )
        for r in rows
    ]
    return Page[InvitationRead](items=items, total=len(items), limit=len(items), offset=0)


@router.post("/invitations/accept", response_model=OrganizationRead)
async def accept_invitation(
    body: InvitationAccept,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> OrganizationRead:
    service = OrganizationService(db)
    org, role = await service.accept_invitation(principal.user, body.token)
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


# -- one org ----------------------------------------------------------------------------


@router.get("/{slug}", response_model=OrganizationRead)
async def get_org(
    slug: str = Path(min_length=1, max_length=100),
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> OrganizationRead:
    summary = await OrganizationService(db).get_by_slug(principal.user.id, slug)
    return _org_read(summary)


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_org(
    slug: str = Path(min_length=1, max_length=100),
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> None:
    service = OrganizationService(db)
    summary = await service.get_by_slug(principal.user.id, slug)
    _require_role(summary, OrgRole.owner)
    await service.delete_organization(summary.organization.id)
    await audit_service.record(
        db,
        action="org.deleted",
        actor_id=principal.user.id,
        actor_email=principal.user.email,
        organization_id=summary.organization.id,
        target_type="organization",
        target_id=summary.organization.id,
    )
    await db.commit()


# -- members ----------------------------------------------------------------------------


@router.get("/{slug}/members", response_model=Page[OrganizationMemberRead])
async def list_members(
    slug: str = Path(min_length=1, max_length=100),
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> Page[OrganizationMemberRead]:
    service = OrganizationService(db)
    summary = await service.get_by_slug(principal.user.id, slug)
    rows = await service.list_members(summary.organization.id)
    items = [
        OrganizationMemberRead(
            user_id=u.id, email=u.email, name=u.name, role=m.role, joined_at=m.joined_at
        )
        for m, u in rows
    ]
    return Page[OrganizationMemberRead](items=items, total=len(items), limit=len(items), offset=0)


@router.patch("/{slug}/members/{user_id}", response_model=OrganizationMemberRead)
async def update_member_role(
    body: OrganizationMemberUpdate,
    slug: str = Path(min_length=1, max_length=100),
    user_id: uuid.UUID = Path(...),
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> OrganizationMemberRead:
    service = OrganizationService(db)
    summary = await service.get_by_slug(principal.user.id, slug)
    _require_role(summary, OrgRole.admin)
    member = await service.set_member_role(summary.organization.id, user_id, body.role)
    rows = await service.list_members(summary.organization.id)
    user = next((u for m, u in rows if m.user_id == user_id), None)
    if user is None:
        raise not_found()
    await audit_service.record(
        db,
        action="org.member_role_changed",
        actor_id=principal.user.id,
        actor_email=principal.user.email,
        organization_id=summary.organization.id,
        target_type="user",
        target_id=user_id,
        detail={"new_role": member.role.value},
    )
    await db.commit()
    return OrganizationMemberRead(
        user_id=user.id, email=user.email, name=user.name, role=member.role, joined_at=member.joined_at
    )


@router.delete("/{slug}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    slug: str = Path(min_length=1, max_length=100),
    user_id: uuid.UUID = Path(...),
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> None:
    service = OrganizationService(db)
    summary = await service.get_by_slug(principal.user.id, slug)
    # Members can remove themselves; otherwise admin+.
    if user_id != principal.user.id:
        _require_role(summary, OrgRole.admin)
    await service.remove_member(summary.organization.id, user_id)
    await audit_service.record(
        db,
        action="org.member_removed",
        actor_id=principal.user.id,
        actor_email=principal.user.email,
        organization_id=summary.organization.id,
        target_type="user",
        target_id=user_id,
    )
    await db.commit()


@router.post("/{slug}/transfer", status_code=status.HTTP_204_NO_CONTENT)
async def transfer_ownership(
    to_user_id: uuid.UUID,
    slug: str = Path(min_length=1, max_length=100),
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> None:
    service = OrganizationService(db)
    summary = await service.get_by_slug(principal.user.id, slug)
    _require_role(summary, OrgRole.owner)
    await service.transfer_ownership(
        summary.organization.id, principal.user.id, to_user_id
    )
    await audit_service.record(
        db,
        action="org.ownership_transferred",
        actor_id=principal.user.id,
        actor_email=principal.user.email,
        organization_id=summary.organization.id,
        target_type="user",
        target_id=to_user_id,
    )
    await db.commit()


# -- invitations ------------------------------------------------------------------------


@router.get("/{slug}/invitations", response_model=Page[InvitationRead])
async def list_invitations(
    slug: str = Path(min_length=1, max_length=100),
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> Page[InvitationRead]:
    service = OrganizationService(db)
    summary = await service.get_by_slug(principal.user.id, slug)
    _require_role(summary, OrgRole.admin)
    rows = await service.list_invitations(summary.organization.id)
    items = [
        InvitationRead(
            id=inv.id,
            organization_id=inv.organization_id,
            organization_slug=summary.organization.slug,
            organization_name=summary.organization.name,
            email=inv.email,
            role=inv.role,
            status=OrganizationService._invitation_status(inv),  # noqa: SLF001
            created_at=inv.created_at,
            expires_at=inv.expires_at,
        )
        for inv in rows
    ]
    return Page[InvitationRead](items=items, total=len(items), limit=len(items), offset=0)


@router.post(
    "/{slug}/invitations", response_model=InvitationCreated, status_code=status.HTTP_201_CREATED
)
async def create_invitation(
    body: InvitationCreate,
    slug: str = Path(min_length=1, max_length=100),
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> InvitationCreated:
    service = OrganizationService(db)
    summary = await service.get_by_slug(principal.user.id, slug)
    _require_role(summary, OrgRole.admin)
    invitation, raw = await service.create_invitation(
        summary.organization.id,
        email=body.email,
        role=body.role,
        invited_by=principal.user.id,
    )
    await audit_service.record(
        db,
        action="org.invitation_created",
        actor_id=principal.user.id,
        actor_email=principal.user.email,
        organization_id=summary.organization.id,
        target_type="organization",
        target_id=summary.organization.id,
        detail={"email": invitation.email, "role": invitation.role.value},
    )
    await db.commit()
    return InvitationCreated(
        id=invitation.id,
        organization_id=invitation.organization_id,
        organization_slug=summary.organization.slug,
        organization_name=summary.organization.name,
        email=invitation.email,
        role=invitation.role,
        status=OrganizationService._invitation_status(invitation),  # noqa: SLF001
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
        token=raw,
    )


@router.delete(
    "/{slug}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def revoke_invitation(
    slug: str = Path(min_length=1, max_length=100),
    invitation_id: uuid.UUID = Path(...),
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> None:
    service = OrganizationService(db)
    summary = await service.get_by_slug(principal.user.id, slug)
    _require_role(summary, OrgRole.admin)
    await service.revoke_invitation(summary.organization.id, invitation_id)
    await audit_service.record(
        db,
        action="org.invitation_revoked",
        actor_id=principal.user.id,
        actor_email=principal.user.email,
        organization_id=summary.organization.id,
        target_type="invitation",
        target_id=invitation_id,
    )
    await db.commit()


# -- projects list and plan ------------------------------------------------------------


@router.get("/{slug}/projects", response_model=Page[ProjectRead])
async def list_org_projects(
    slug: str = Path(min_length=1, max_length=100),
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> Page[ProjectRead]:
    service = OrganizationService(db)
    summary = await service.get_by_slug(principal.user.id, slug)
    projects = await service.list_projects(summary.organization.id)
    items = [ProjectRead.model_validate(p) for p in projects]
    return Page[ProjectRead](items=items, total=len(items), limit=len(items), offset=0)


@router.get("/{slug}/plan", response_model=OrgPlanRead)
async def get_org_plan(
    slug: str = Path(min_length=1, max_length=100),
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> OrgPlanRead:
    service = OrganizationService(db)
    summary = await service.get_by_slug(principal.user.id, slug)
    plan, sub = await service.plan_and_subscription(summary.organization.id)
    usage = await service.usage(summary.organization.id, viewer_id=principal.user.id)
    return OrgPlanRead(
        plan=PlanRead.model_validate(plan),
        subscription=SubscriptionRead.model_validate(sub),
        usage=OrgUsage(**usage),
        checkout_available=checkout_available(),
        upgrades=[
            PlanRead.model_validate(p) for p in await BillingService(db).upgrade_options(plan.id)
        ],
        portal_available=portal_available(sub),
    )


# -- billing (Phase B: Checkout only — the webhook that applies the plan is Phase C) ------


@router.post(
    "/{slug}/billing/checkout",
    response_model=CheckoutRead,
    status_code=status.HTTP_201_CREATED,
)
async def start_checkout(
    body: CheckoutCreate,
    slug: str = Path(min_length=1, max_length=100),
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> CheckoutRead:
    service = OrganizationService(db)
    summary = await service.get_by_slug(principal.user.id, slug)
    _require_role(summary, OrgRole.admin)
    session = await BillingService(db).start_checkout(
        summary.organization, plan_id=body.plan_id, actor=principal.user
    )
    return CheckoutRead(id=session.id, url=session.url)


@router.post(
    "/{slug}/billing/portal",
    response_model=PortalRead,
    status_code=status.HTTP_201_CREATED,
)
async def open_billing_portal(
    slug: str = Path(min_length=1, max_length=100),
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> PortalRead:
    """Stripe Billing Portal for a paying org: change plan, update the card, cancel. The
    resulting changes reach the platform through the webhook, not through this call."""
    service = OrganizationService(db)
    summary = await service.get_by_slug(principal.user.id, slug)
    _require_role(summary, OrgRole.admin)
    url = await BillingService(db).start_portal(summary.organization, actor=principal.user)
    return PortalRead(url=url)
