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
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import AccountStatus, AuditResult, MemberRole, PlatformRole, TokenAudience
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

    __table_args__ = (
        CheckConstraint("email = lower(email)", name="ck_platform_users_email_lower"),
    )


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

    __table_args__ = (Index("ix_platform_refresh_family", "family_id"),)


class ApiToken(UUIDPrimaryKeyMixin, Base):
    """A personal access token: for scripts, CI and MCP clients. Only its hash is kept."""

    __tablename__ = "platform_api_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (Index("ix_project_members_user", "user_id"),)


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
    )
