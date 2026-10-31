"""Request/response schemas for Phase A — Organizations core."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    AccountStatus,
    AuditResult,
    MemberRole,
    OrgKind,
    OrgRole,
    SubscriptionStatus,
)

_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]*$")


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    slug: str | None = Field(default=None, max_length=100)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        if value is not None and not _SLUG_RE.match(value):
            raise ValueError(
                "slug must be lowercase letters, digits and hyphens, starting with a letter"
            )
        return value


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    kind: OrgKind
    created_at: datetime
    my_role: OrgRole
    member_count: int = 0
    # Set while a deletion request waits for its grace period to end (access is blocked).
    deletion_requested_at: datetime | None = None
    deletion_scheduled_for: datetime | None = None
    # §8 Security policies (visible to every member, so the UI can explain a 403).
    require_mfa: bool = False
    session_ttl_hours: int | None = None


class OrganizationMemberRead(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str
    role: OrgRole
    joined_at: datetime
    # §8 People table: status, 2FA on/off (built-in TOTP, §4.4), last sign-in.
    status: AccountStatus = AccountStatus.active
    last_login_at: datetime | None = None
    mfa_enabled: bool | None = None


class OrgPoliciesRead(BaseModel):
    """§8 Security policies. `session_ttl_hours` None = the platform default
    (`default_session_hours`)."""

    require_mfa: bool
    session_ttl_hours: int | None
    members_without_mfa: int
    default_session_hours: int
    # §7.1: platform staff may "view as" a member only while this is on (default on).
    allow_impersonation: bool = True


class OrgPoliciesUpdate(BaseModel):
    """Only the fields sent change. `session_ttl_hours: null` goes back to the default."""

    require_mfa: bool | None = None
    session_ttl_hours: int | None = Field(default=None, ge=1, le=720)
    allow_impersonation: bool | None = None


class OrganizationMemberUpdate(BaseModel):
    role: OrgRole


_EMAIL_SHAPE = re.compile(r"[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]{2,}")


class InvitationCreate(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    role: OrgRole = OrgRole.member

    @field_validator("email")
    @classmethod
    def _looks_like_an_email(cls, value: str) -> str:
        value = value.strip()
        if not _EMAIL_SHAPE.fullmatch(value):
            raise ValueError("must be a valid e-mail address")
        return value


class InvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    organization_slug: str = ""
    organization_name: str = ""
    email: str
    role: OrgRole
    status: str  # computed: 'pending' | 'accepted' | 'revoked' | 'expired'
    created_at: datetime
    expires_at: datetime


class InvitationCreated(InvitationRead):
    token: str  # shown exactly once
    invite_url: str = ""  # <public_app_url>/#/invite/<token>
    emailed: bool = False  # False when the platform has no SMTP configured


class OrgProjectJoin(BaseModel):
    role: MemberRole = MemberRole.editor


class ProjectTransfer(BaseModel):
    to_slug: str = Field(min_length=1, max_length=100)


class OrgAuditRead(BaseModel):
    """An org admin's view of the audit log (§8). No `detail` and no client IP: §7.1 keeps
    request details that can contain customer data out of shared views."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    at: datetime
    actor_email: str | None
    via: str
    action: str
    target_type: str | None
    target_id: str | None
    project_id: uuid.UUID | None
    result: AuditResult


class InvitationAccept(BaseModel):
    token: str = Field(min_length=16, max_length=128)


class PlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    max_seats: int | None
    max_projects: int | None
    max_api_tokens: int | None
    max_mcp_tokens: int | None
    allow_sso: bool
    allow_scim: bool
    allow_mcp: bool
    monthly_price_usd: int
    is_public: bool


class SubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: uuid.UUID
    plan_id: str
    status: SubscriptionStatus
    trial_ends_at: datetime | None
    current_period_end: datetime | None
    seat_override: int | None
    project_override: int | None


class OrgUsage(BaseModel):
    seats_used: int
    seats_cap: int | None
    pending_invites: int
    projects_used: int
    projects_cap: int | None
    api_tokens_used: int = 0  # the viewer's own active tokens in this org
    api_tokens_cap: int | None = None  # per member
    mcp_tokens_used: int = 0  # every member's MCP tokens in this org
    mcp_tokens_cap: int | None = None


class OrgPlanRead(BaseModel):
    plan: PlanRead
    subscription: SubscriptionRead
    usage: OrgUsage
    checkout_available: bool = False  # Stripe configured on this platform
    upgrades: list[PlanRead] = []  # plans purchasable via Checkout, excluding the current
    portal_available: bool = False  # org has a Stripe Customer → 'Manage billing'


# -- billing (Phase B: Checkout only) ---------------------------------------------------


class CheckoutCreate(BaseModel):
    plan_id: str = Field(min_length=1, max_length=40)


class CheckoutRead(BaseModel):
    id: str
    url: str


class PortalRead(BaseModel):
    url: str
