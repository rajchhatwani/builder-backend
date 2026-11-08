"""SCIM 2.0 directory sync per organization (PLATFORM_SAAS_PLAN §2.1 ScimDirectory, §3.1, §4.3).

Independent of SSO (§14 "Separate SCIM from SSO"): an org can have either, both or neither.
`scim_directories` is the §3.1 table plus what the setup page shows (token hint, the
group → role dictionary of §12.E.3). `scim_users` / `scim_groups` are the resources the IdP
manages; their ids are what the IdP stores, so they're per-org, not the Builder account's id.
Only the bearer token's SHA-256 is kept.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ScimDirectory(Base):
    __tablename__ = "scim_directories"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    bearer_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # The token's last characters, so admins can tell which one an IdP holds. Not a secret.
    token_hint: Mapped[str] = mapped_column(String(12), nullable=False, default="")
    token_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # §12.E.3: SCIM group display name (lower-cased) -> org role ('owner' | 'admin' | 'member').
    # Empty = groups don't change roles; people provisioned by SCIM join as members.
    group_roles: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScimUser(Base):
    """A person the org's directory provisioned (or linked). Stays after deactivation
    (`active=false`, no org membership) so the IdP can still read and reactivate it."""

    __tablename__ = "scim_users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="CASCADE"), nullable=False
    )
    user_name: Mapped[str] = mapped_column(String(254), nullable=False)  # as the IdP sent it
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    given_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    family_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        Index("uq_scim_users_org_user", "organization_id", "user_id", unique=True),
        Index("uq_scim_users_org_user_name", "organization_id", func.lower(user_name), unique=True),
    )


class ScimGroup(Base):
    __tablename__ = "scim_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        Index("uq_scim_groups_org_name", "organization_id", func.lower(display_name), unique=True),
    )


class ScimGroupMember(Base):
    __tablename__ = "scim_group_members"

    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scim_groups.id", ondelete="CASCADE"), primary_key=True
    )
    scim_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scim_users.id", ondelete="CASCADE"), primary_key=True
    )

    __table_args__ = (Index("ix_scim_group_members_user", "scim_user_id"),)
