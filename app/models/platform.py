"""Tables for the builder's own accounts, sessions, API tokens, memberships and audit trail."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import (
    AccountStatus,
    AuditResult,
    MemberRole,
    OrgKind,
    OrgRole,
    PlatformRole,
    SubscriptionStatus,
    TokenAudience,
)
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PlatformUser(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "platform_users"

    # Always stored lower-cased and trimmed; the unique index therefore is case-insensitive.
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[AccountStatus] = mapped_column(
        SAEnum(AccountStatus, name="account_status", native_enum=False, length=20),
        nullable=False,
        default=AccountStatus.active,
    )
    platform_role: Mapped[PlatformRole] = mapped_column(
        SAEnum(PlatformRole, name="platform_role", native_enum=False, length=20),
        nullable=False,
        default=PlatformRole.customer,
    )
    # Bumped to invalidate every access token this person holds (password change, suspend, ...).
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_logins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    # Set when an administrator chose the password: it must be replaced before anything else.
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Which org to drop the user into after login when they belong to several.
    default_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    # Set once the person proved they control the mailbox (invite link, SSO or SCIM sign-in).
    # Sign-up alone never sets it, so an address someone merely typed in is not yet theirs.
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Built-in TOTP (§4.4 Phase 1). The secret is encrypted with app.core.crypto; it is set at
    # setup and only counts once `totp_enabled_at` is set (the person proved a code).
    totp_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The last accepted time step: a code is never accepted twice.
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        CheckConstraint("email = lower(email)", name="ck_platform_users_email_lower"),
    )

    @property
    def mfa_enabled(self) -> bool:
        return self.totp_enabled_at is not None


class MfaRecoveryCode(UUIDPrimaryKeyMixin, Base):
    """A one-time backup code (stored as SHA-256), for a person who lost their authenticator."""

    __tablename__ = "mfa_recovery_codes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="CASCADE"), nullable=False
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_mfa_recovery_codes_user", "user_id"),)


class RefreshToken(UUIDPrimaryKeyMixin, Base):
    """One rotation step of a login session. A `family` is the whole chain from one login."""

    __tablename__ = "platform_refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="CASCADE"), nullable=False
    )
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    audience: Mapped[TokenAudience] = mapped_column(
        SAEnum(TokenAudience, name="token_audience", native_enum=False, length=10), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # How the login family was authenticated, space-separated: 'pwd', 'pwd otp', 'sso'. Copied
    # into each access token (`amr`) so the org MFA policy can check it (§4.4).
    auth_methods: Mapped[str] = mapped_column(String(40), nullable=False, default="pwd")
    # When the person signed in (the first token of the family): the org session-TTL cap (§8)
    # counts from here, however often the token rotates.
    family_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_platform_refresh_family", "family_id"),)


class ApiToken(UUIDPrimaryKeyMixin, Base):
    """A personal access token: for scripts, CI and MCP clients. Only its hash is kept."""

    __tablename__ = "platform_api_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Public lookup id embedded in the token (not secret); the secret part is only hashed.
    public_id: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    # When set, the token can only act on this one project.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_mcp_use_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProjectMember(Base):
    """Who may touch a project. The creator is its first `owner`; a project always keeps one."""

    __tablename__ = "project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[MemberRole] = mapped_column(
        SAEnum(MemberRole, name="member_role", native_enum=False, length=10), nullable=False
    )
    # When True, this member may use the MCP endpoint on this project.
    # Defaults to False: the project owner must explicitly grant access.
    mcp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (Index("ix_project_members_user", "user_id"),)


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A customer tenant. Every project and every org-scoped resource lives inside one of these.

    A single-user ('individual') account is just an Organization with kind='personal' and one
    owner. The code paths never fork on kind; the UI hides concepts (invites, SSO) that make
    no sense for a solo org.
    """

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    kind: Mapped[OrgKind] = mapped_column(
        SAEnum(OrgKind, name="org_kind", native_enum=False, length=20),
        nullable=False,
        default=OrgKind.team,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Deletion is a request (owner decision): access is blocked from `deletion_requested_at`;
    # the owner can revoke until `deletion_scheduled_for`, when the org and its projects go.
    deletion_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deletion_scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deletion_requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True
    )
    # §8 Security policies. require_mfa: members' sessions must have used MFA (TOTP or SSO) to
    # reach this org's routes and projects. session_ttl_hours: members sign in again after this
    # long (counted from sign-in, not from the last refresh); None = the platform default.
    require_mfa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    session_ttl_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "session_ttl_hours IS NULL OR (session_ttl_hours BETWEEN 1 AND 720)",
            name="ck_organizations_session_ttl",
        ),
    )


class OrganizationMember(Base):
    """Who sits in an org and what they may do inside it.

    `(organization_id, user_id)` is the natural key: a user can be in many orgs, each with its
    own role, and never twice in the same one.
    """

    __tablename__ = "organization_members"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[OrgRole] = mapped_column(
        SAEnum(OrgRole, name="org_role", native_enum=False, length=20),
        nullable=False,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (Index("ix_organization_members_user", "user_id"),)


class OrganizationInvitation(UUIDPrimaryKeyMixin, Base):
    """A pending seat. The caller gets the raw token exactly once; only its hash is kept."""

    __tablename__ = "organization_invitations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    role: Mapped[OrgRole] = mapped_column(
        SAEnum(OrgRole, name="org_role", native_enum=False, length=20),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_organization_invitations_org", "organization_id"),
        Index("ix_organization_invitations_email", "email"),
    )


class Plan(Base):
    """A plan is a row describing what a Subscription on it allows.

    Plans are platform-defined and seeded. Caps are nullable (NULL = unlimited), but we never
    ship NULL caps on free/team: that is a trap when the business later wants to charge for a
    knob they already gave away.
    """

    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    max_seats: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_projects: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_api_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_mcp_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    allow_sso: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_scim: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_mcp: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    monthly_price_usd: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class Subscription(Base):
    """One active subscription row per org, pointing at the current Plan.

    Stripe fields are nullable because free/team plans do not create a Stripe customer. The
    `seat_override` is what the platform operator can bump above the plan's own cap.
    """

    __tablename__ = "subscriptions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    plan_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        SAEnum(SubscriptionStatus, name="subscription_status", native_enum=False, length=20),
        nullable=False,
        default=SubscriptionStatus.active,
    )
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    seat_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    project_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class AuditLog(Base):
    """Append-only record of who did what. No foreign keys: rows outlive users and projects.

    The migration adds a trigger that rejects UPDATE and DELETE. Never store secrets, passwords,
    tokens or request bodies here: only ids, the action name and a short non-sensitive `detail`.
    """

    __tablename__ = "platform_audit_log"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    via: Mapped[str] = mapped_column(String(10), nullable=False, default="session")
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    result: Mapped[AuditResult] = mapped_column(
        SAEnum(AuditResult, name="audit_result", native_enum=False, length=10), nullable=False
    )
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_platform_audit_at", "at"),
        Index("ix_platform_audit_actor", "actor_id", "at"),
        Index("ix_platform_audit_project", "project_id", "at"),
        Index("ix_platform_audit_org", "organization_id", "at"),
        # Stripe webhook dedupe looks events up by (action, target_id).
        Index("ix_platform_audit_action_target", "action", "target_id"),
    )
