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


class SessionRead(BaseModel):
    """Access token in the body (the app keeps it in memory); the refresh token is a cookie."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserRead


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
