"""Pydantic schemas for project auth configuration (builder API layer)."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import (
    DeletionMode,
    JwtAlgorithm,
    SmsProvider,
    TokenStore,
)

# ── SMTP config sub-schema ────────────────────────────────────────────────────


class SmtpConfig(BaseModel):
    """SMTP server settings embedded in auth config.

    Credentials (password) are never stored here; they live in env vars of
    the generated project.
    """

    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535, default=587)
    use_tls: bool = True
    from_email: str = Field(min_length=5, max_length=255)
    from_name: str = Field(min_length=1, max_length=100)

    @field_validator("from_email")
    @classmethod
    def validate_from_email(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("from_email must be a valid email address")
        return v


# ── SMS config sub-schema ─────────────────────────────────────────────────────


class SmsConfig(BaseModel):
    """Non-secret SMS provider settings.

    from_number follows E.164 format (+<country><number>).
    Actual API credentials (auth_token, API key) must live in env vars.
    """

    from_number: str = Field(min_length=5, max_length=20)


# ── Rate limit string pattern ─────────────────────────────────────────────────

_RATE_PATTERN = r"^[0-9]{1,6}/[0-9]{0,4}(second|minute|hour|day)s?$"


# ── AuthConfig Create / Update ────────────────────────────────────────────────


class AuthConfigCreate(BaseModel):
    """Request body for POST /projects/{id}/auth."""

    enabled: bool = True

    # Token
    token_store: TokenStore = TokenStore.db
    access_token_ttl_minutes: int = Field(default=15, ge=1, le=1440)  # max 24h
    refresh_token_ttl_days: int = Field(default=7, ge=1, le=365)
    jwt_algorithm: JwtAlgorithm = JwtAlgorithm.hs256

    # Password reset
    email_magic_link_enabled: bool = True
    sms_otp_enabled: bool = False
    otp_ttl_minutes: int = Field(default=10, ge=1, le=60)

    # Registration
    email_verification_required: bool = True
    invite_only: bool = False
    multi_tenant: bool = False

    # User lifecycle
    deletion_mode: DeletionMode = DeletionMode.soft

    # SMTP (required when email_magic_link_enabled=True)
    smtp_config: SmtpConfig | None = None

    # SMS (required when sms_otp_enabled=True)
    sms_provider: SmsProvider | None = None
    sms_config: SmsConfig | None = None

    # Rate limiting
    login_rate_limit: str = Field(
        default="5/15minutes", pattern=_RATE_PATTERN, max_length=50
    )
    register_rate_limit: str = Field(
        default="10/hour", pattern=_RATE_PATTERN, max_length=50
    )
    reset_rate_limit: str = Field(
        default="3/hour", pattern=_RATE_PATTERN, max_length=50
    )

    # Branding
    security_headers_enabled: bool = True
    app_name: str | None = Field(default=None, max_length=100)
    app_url: str | None = Field(default=None, max_length=2000)

    # Custom email templates (HTML strings per email type)
    email_templates: Annotated[dict[str, Any] | None, Field(default=None)] = None

    @model_validator(mode="after")
    def check_smtp_when_email_enabled(self) -> "AuthConfigCreate":
        if self.email_magic_link_enabled and self.smtp_config is None:
            raise ValueError(
                "smtp_config is required when email_magic_link_enabled is true"
            )
        return self

    @model_validator(mode="after")
    def check_sms_when_otp_enabled(self) -> "AuthConfigCreate":
        if self.sms_otp_enabled and (
            self.sms_provider is None or self.sms_config is None
        ):
            raise ValueError(
                "sms_provider and sms_config are required when sms_otp_enabled is true"
            )
        return self



class AuthConfigUpdate(BaseModel):
    """Request body for PATCH /projects/{id}/auth.

    All fields optional — only supplied fields are updated.
    Cross-field rules are re-checked after merging current state with the patch.
    """

    enabled: bool | None = None
    token_store: TokenStore | None = None
    access_token_ttl_minutes: int | None = Field(default=None, ge=1, le=1440)
    refresh_token_ttl_days: int | None = Field(default=None, ge=1, le=365)
    jwt_algorithm: JwtAlgorithm | None = None
    email_magic_link_enabled: bool | None = None
    sms_otp_enabled: bool | None = None
    otp_ttl_minutes: int | None = Field(default=None, ge=1, le=60)
    email_verification_required: bool | None = None
    invite_only: bool | None = None
    multi_tenant: bool | None = None
    deletion_mode: DeletionMode | None = None
    smtp_config: SmtpConfig | None = None
    sms_provider: SmsProvider | None = None
    sms_config: SmsConfig | None = None
    login_rate_limit: str | None = Field(
        default=None, pattern=_RATE_PATTERN, max_length=50
    )
    register_rate_limit: str | None = Field(
        default=None, pattern=_RATE_PATTERN, max_length=50
    )
    reset_rate_limit: str | None = Field(
        default=None, pattern=_RATE_PATTERN, max_length=50
    )
    security_headers_enabled: bool | None = None
    app_name: str | None = Field(default=None, max_length=100)
    app_url: str | None = Field(default=None, max_length=2000)
    email_templates: dict[str, Any] | None = None


# ── AuthConfig Read ───────────────────────────────────────────────────────────


class AuthConfigRead(BaseModel):
    """Response body for auth config endpoints."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    project_id: uuid.UUID
    enabled: bool
    token_store: TokenStore
    access_token_ttl_minutes: int
    refresh_token_ttl_days: int
    jwt_algorithm: JwtAlgorithm
    email_magic_link_enabled: bool
    sms_otp_enabled: bool
    otp_ttl_minutes: int
    email_verification_required: bool
    invite_only: bool
    multi_tenant: bool
    deletion_mode: DeletionMode
    smtp_config: SmtpConfig | None
    sms_provider: SmsProvider | None
    sms_config: SmsConfig | None
    login_rate_limit: str
    register_rate_limit: str
    reset_rate_limit: str
    security_headers_enabled: bool
    app_name: str | None
    app_url: str | None
    email_templates: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
