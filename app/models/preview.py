"""Preview runtime tables (B3-10): previews + admin-configurable limits."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin, _utcnow

LIVE_STATES = ("starting", "running", "stopping", "sleeping")
STATES = (*LIVE_STATES, "expired", "failed", "killed")


class Preview(UUIDPrimaryKeyMixin, Base):
    """One API-only preview of a project: generated code + own Postgres in sandboxes.

    The row id is the public, unguessable preview id (uuid4). The access token is shown once
    and only its SHA-256 is stored."""

    __tablename__ = "previews"
    __table_args__ = (
        Index("ix_previews_project", "project_id", "created_at"),
        Index("ix_previews_owner_state", "created_by", "state"),
        Index("ix_previews_state_expiry", "state", "expires_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True
    )
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="starting")
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    spec_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Sandbox ids (hex) of the database and the app container; the network is owned by db_sandbox.
    db_sandbox: Mapped[str] = mapped_column(String(32), nullable=False)
    app_sandbox: Mapped[str] = mapped_column(String(32), nullable=False)
    app_ip: Mapped[str | None] = mapped_column(String(15), nullable=True)
    code_dir: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Limits in force when the preview was created (cpu, memory, db size, idle minutes).
    limits: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    wake_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    last_request_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state_since: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class PreviewPlatformSettings(Base):
    """Singleton row (id=1): the global kill switch and the platform default limits."""

    __tablename__ = "preview_platform_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    kill_switch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    limits: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class PreviewOrgLimits(UUIDPrimaryKeyMixin, Base):
    """Per-organization override of the platform defaults (only the keys present apply)."""

    __tablename__ = "preview_org_limits"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # False: the override may only lower the platform defaults, never exceed them.
    allow_above_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    limits: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
