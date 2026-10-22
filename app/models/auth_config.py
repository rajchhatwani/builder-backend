import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import (
    DeletionMode,
    JwtAlgorithm,
    SmsProvider,
    TokenStore,
)
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ProjectAuthConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Auth configuration for a single generated project (1:1 with projects).

    SMTP credentials are stored as JSONB (host, port, use_tls, from_email, from_name).
    Actual secrets (SMTP password, SMS API keys) must live in the generated project's
    environment variables; they are never stored here.
    """

    __tablename__ = "project_auth_configs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # enforces the 1:1 relationship at the DB level
    )

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # ── Token settings ────────────────────────────────────────────────────────
    token_store: Mapped[TokenStore] = mapped_column(
        SAEnum(TokenStore, name="token_store", native_enum=False, length=10),
        nullable=False,
        default=TokenStore.db,
    )
    access_token_ttl_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=15
    )
    refresh_token_ttl_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=7
    )
    jwt_algorithm: Mapped[JwtAlgorithm] = mapped_column(
        SAEnum(JwtAlgorithm, name="jwt_algorithm", native_enum=False, length=10),
        nullable=False,
        default=JwtAlgorithm.hs256,
    )

    # ── Password reset ────────────────────────────────────────────────────────
    email_magic_link_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    sms_otp_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    otp_ttl_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=10)

    # ── Registration ──────────────────────────────────────────────────────────
    email_verification_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    # ── User lifecycle ────────────────────────────────────────────────────────
    deletion_mode: Mapped[DeletionMode] = mapped_column(
        SAEnum(DeletionMode, name="deletion_mode", native_enum=False, length=10),
        nullable=False,
        default=DeletionMode.soft,
    )

    # ── SMTP (host, port, use_tls, from_email, from_name) ────────────────────
    smtp_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # ── SMS ───────────────────────────────────────────────────────────────────
    sms_provider: Mapped[SmsProvider | None] = mapped_column(
        SAEnum(SmsProvider, name="sms_provider", native_enum=False, length=15),
        nullable=True,
    )
    # from_number and other non-secret provider config (secrets are env-only)
    sms_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # ── Invite-only mode ──────────────────────────────────────────────────────
    invite_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Tenant support ────────────────────────────────────────────────────────
    multi_tenant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Rate limiting (stored as plain text notes; implementation via generated code) ─
    # Configurable limits are stored so the generator can embed them in templates.
    login_rate_limit: Mapped[str] = mapped_column(
        String(50), nullable=False, default="5/15minutes"
    )
    register_rate_limit: Mapped[str] = mapped_column(
        String(50), nullable=False, default="10/hour"
    )
    reset_rate_limit: Mapped[str] = mapped_column(
        String(50), nullable=False, default="3/hour"
    )

    # ── Security headers ──────────────────────────────────────────────────────
    security_headers_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )

    # ── Branding ──────────────────────────────────────────────────────────────
    app_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    app_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Notes / custom template overrides ─────────────────────────────────────
    # Reserved for future email template customisation (raw HTML per type).
    email_templates: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
