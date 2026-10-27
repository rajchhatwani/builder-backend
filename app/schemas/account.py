import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AccountStatus, AuditResult, MemberRole, PlatformRole

# Passwords are length-capped here too so an enormous body is rejected before it is hashed.
_PASSWORD = Field(min_length=1, max_length=256, repr=False)


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = _PASSWORD
    name: str = Field(default="", max_length=100)


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=254)
    password: str = _PASSWORD


class PasswordChangeRequest(BaseModel):
    current_password: str = _PASSWORD
    new_password: str = _PASSWORD


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    platform_role: PlatformRole
    status: AccountStatus
    must_change_password: bool
    created_at: datetime
    last_login_at: datetime | None
    # §3.2: where the UI lands someone who belongs to several orgs.
    default_organization_id: uuid.UUID | None = None
    # §4.4: built-in TOTP is on (People tables show it as "2FA on/off").
    mfa_enabled: bool = False


class DefaultOrganizationUpdate(BaseModel):
    organization_id: uuid.UUID


class SessionRead(BaseModel):
    """Access token in the body (the app keeps it in memory); the refresh token is a cookie."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserRead


# -- MFA (§4.4 Phase 1) ---------------------------------------------------------------------

_CODE = Field(min_length=1, max_length=32, repr=False)
_MFA_TOKEN = Field(min_length=1, max_length=2048, repr=False)


class MfaChallengeRead(BaseModel):
    """The answer to a correct password when a second step is needed. No session yet.

    `enrollment_required`: the account must set up TOTP first (platform staff without it): call
    `…/login/mfa/setup` then `…/login/mfa/enable`. Otherwise send a code to `…/login/mfa`.
    """

    mfa_required: bool = True
    enrollment_required: bool = False
    mfa_token: str
    expires_in: int
    methods: list[str] = ["totp", "recovery_code"]


class MfaLoginRequest(BaseModel):
    mfa_token: str = _MFA_TOKEN
    code: str = _CODE  # a 6-digit TOTP code or a recovery code


class MfaTokenRequest(BaseModel):
    mfa_token: str = _MFA_TOKEN


class TotpSetupRequest(BaseModel):
    password: str = _PASSWORD


class TotpSetupRead(BaseModel):
    """Shown once while setting up: the secret for manual entry and the URI for a QR code."""

    secret: str
    otpauth_uri: str


class MfaCodeRequest(BaseModel):
    code: str = _CODE


class MfaDisableRequest(BaseModel):
    password: str = _PASSWORD
    code: str = _CODE


class RecoveryCodesRead(BaseModel):
    """Shown once. Each code works one time instead of an authenticator code."""

    recovery_codes: list[str]


class SessionWithRecoveryCodesRead(SessionRead):
    """TOTP was just turned on: a fresh session that counts as MFA'd, plus the backup codes."""

    recovery_codes: list[str]


class MfaOrgRequirement(BaseModel):
    organization_id: uuid.UUID
    slug: str
    name: str


class MfaStatusRead(BaseModel):
    totp_enabled: bool
    enabled_at: datetime | None
    recovery_codes_left: int
    # Whether this session itself used a second factor (an org requiring MFA checks this).
    session_mfa: bool
    # Why MFA can't be turned off: platform staff always need it; orgs may require it.
    required_for_staff: bool
    required_by: list[MfaOrgRequirement]
    sso_only: bool


# -- API tokens ----------------------------------------------------------------------------


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=255)
    scopes: list[str] = Field(min_length=1, max_length=8)
    expires_in_days: int = Field(default=90, ge=1, le=365)
    project_id: uuid.UUID | None = None


class ApiTokenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    public_id: str
    scopes: list[str]
    project_id: uuid.UUID | None
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    last_mcp_use_at: datetime | None
    revoked_at: datetime | None


class ApiTokenCreated(ApiTokenRead):
    token: str  # shown exactly once


class ProjectTokenRead(ApiTokenRead):
    """An API token as seen by a project owner — includes whose token it is."""

    user_id: uuid.UUID
    user_email: str


# -- project members -----------------------------------------------------------------------


class MemberRead(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str
    role: MemberRole
    mcp_enabled: bool
    created_at: datetime


class MemberAdd(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    role: MemberRole = MemberRole.viewer
    mcp_enabled: bool = False


class MemberUpdate(BaseModel):
    role: MemberRole


class MemberMcpUpdate(BaseModel):
    mcp_enabled: bool


# -- admin console -------------------------------------------------------------------------


class AdminUserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(default="", max_length=100)
    platform_role: PlatformRole = PlatformRole.customer
    # Omit to have a strong temporary password generated and returned once.
    password: str | None = Field(default=None, max_length=256, repr=False)


class AdminUserUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    status: AccountStatus | None = None
    platform_role: PlatformRole | None = None


class AdminUserRead(UserRead):
    failed_logins: int
    locked_until: datetime | None
    project_count: int = 0


class AdminUserCreated(BaseModel):
    user: AdminUserRead
    temporary_password: str | None = None  # present only when the server generated it


class AdminProjectRead(BaseModel):
    """Metadata only. Administrators run the platform; they do not get to read customer specs."""

    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime
    owner_emails: list[str]
    entity_count: int


class AuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    at: datetime
    actor_id: uuid.UUID | None
    actor_email: str | None
    via: str
    action: str
    target_type: str | None
    target_id: str | None
    project_id: uuid.UUID | None
    organization_id: uuid.UUID | None = None
    result: AuditResult
    client_ip: str | None
    detail: dict[str, object] | None


class AdminStats(BaseModel):
    users: int
    active_users: int
    suspended_users: int
    admins: int
    projects: int
    api_tokens: int
    failed_logins_24h: int


class AdminOrgRead(BaseModel):
    """Operator-facing view of an organization: metadata, counts, plan, status."""

    id: uuid.UUID
    name: str
    slug: str
    kind: str  # OrgKind.value
    created_at: datetime
    deleted_at: datetime | None
    member_count: int
    project_count: int
    plan_id: str
    status: str  # SubscriptionStatus.value
    seat_override: int | None
    project_override: int | None
    # §7: Stripe deep link, MRR and last activity on the Organizations tab.
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    current_period_end: datetime | None = None
    trial_ends_at: datetime | None = None
    mrr_cents: int = 0
    last_activity_at: datetime | None = None
    deletion_requested_at: datetime | None = None
    deletion_scheduled_for: datetime | None = None
    # §12.D.5 SSO status column (None protocol = no connection) and §8 policies.
    sso_protocol: str | None = None
    sso_active: bool = False
    sso_verified_domains: int = 0
    sso_last_test_at: datetime | None = None
    sso_last_test_result: str | None = None
    # §12.E.4 SCIM status column.
    scim_configured: bool = False
    scim_active: bool = False
    scim_users: int = 0  # active SCIM-provisioned people
    scim_last_sync_at: datetime | None = None
    scim_token_created_at: datetime | None = None
    require_mfa: bool = False
    session_ttl_hours: int | None = None


class AdminOrgDeletionUpdate(BaseModel):
    """Give a pending deletion request a different grace period, counted from now."""

    grace_days: int = Field(ge=0, le=3650)
    reason: str = Field(min_length=1, max_length=255)


class AdminReason(BaseModel):
    reason: str = Field(min_length=1, max_length=255)


class AdminOrgPlanChange(BaseModel):
    """A manual plan change, for orgs not billed through Stripe. Needs a reason (§6.5)."""

    plan_id: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=255)


class AdminOrgMemberRead(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str
    role: str
    joined_at: datetime
    status: AccountStatus
    last_login_at: datetime | None
    mfa_enabled: bool = False


class AdminOrgProjectRead(BaseModel):
    """Metadata only (§7.1): never spec contents."""

    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime
    entity_count: int


class AdminSubscriptionRead(BaseModel):
    organization_id: uuid.UUID
    organization_slug: str
    organization_name: str
    plan_id: str
    status: str
    current_period_end: datetime | None
    trial_ends_at: datetime | None
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    seat_override: int | None
    updated_at: datetime


class DayCount(BaseModel):
    day: str  # ISO date
    count: int


class AdminInsights(BaseModel):
    """§7 Insights: reporting over data the platform already keeps; no new tracking."""

    signups_per_day: list[DayCount]  # last 30 days
    orgs_per_day: list[DayCount]  # team orgs created, last 30 days
    total_orgs: int
    active_orgs_7d: int  # orgs with any successful write in the audit log
    total_projects: int
    mcp_calls_24h: int
    denied_by_quota_7d: int


class AdminOrgSeatOverride(BaseModel):
    """Operator sets a per-org seat override above the plan cap, with a reason."""

    seat_override: int | None = Field(default=None, ge=0, le=100000)
    project_override: int | None = Field(default=None, ge=0, le=100000)
    reason: str = Field(min_length=1, max_length=255)


class PlanWrite(BaseModel):
    """Operator-facing plan editor. The id is immutable once created."""

    display_name: str = Field(min_length=1, max_length=100)
    max_seats: int | None = Field(default=None, ge=0, le=100000)
    max_projects: int | None = Field(default=None, ge=0, le=100000)
    max_api_tokens: int | None = Field(default=None, ge=0, le=100000)
    max_mcp_tokens: int | None = Field(default=None, ge=0, le=100000)
    allow_sso: bool = False
    allow_scim: bool = False
    allow_mcp: bool = False
    monthly_price_usd: int = Field(default=0, ge=0, le=10_000_000)
    is_public: bool = True


class PlatformSettingsRead(BaseModel):
    environment: str
    signup_mode: str
    access_token_minutes: int
    refresh_token_days: int
    admin_refresh_token_hours: int
    login_max_failures: int
    lockout_minutes: int
    trust_proxy_headers: bool
    docs_enabled: bool
    cors_origins: list[str]
