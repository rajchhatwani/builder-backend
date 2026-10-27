"""Enterprise SSO per organization (PLATFORM_SAAS_PLAN §3.1, §4.2).

One connection per org (SAML or OIDC), one or more DNS-verified e-mail domains, and the short-lived
state of a login in flight. Nothing here holds a secret in clear: the OIDC client secret is
encrypted with `app.core.crypto`, and IdP certificates are public by nature but still never audited.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SsoConnection(Base):
    __tablename__ = "sso_connections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    protocol: Mapped[str] = mapped_column(String(10), nullable=False)  # 'saml' | 'oidc'
    idp_entity_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    idp_sso_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    idp_cert_pem: Mapped[str | None] = mapped_column(Text, nullable=True)
    oidc_discovery_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    oidc_client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oidc_client_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # §12.D.4 "allowed roles for JIT": whether unknown people are created on first login, and
    # with which org role ('member' or 'admin'; never 'owner').
    jit_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    jit_role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    # OIDC: accept ID tokens that carry no `email_verified` claim (Entra ID sends none). Off by
    # default: only safe when users can't edit their own e-mail address at the IdP.
    trust_unverified_email: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # The last "test with my own e-mail" round trip (§12.D.6): when, by whom, and 'ok' or the
    # failure reason. Shown to org admins and to operators (§12.D.5).
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_result: Mapped[str | None] = mapped_column(String(60), nullable=True)
    last_tested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        CheckConstraint("protocol IN ('saml', 'oidc')", name="ck_sso_connections_protocol"),
        CheckConstraint("jit_role IN ('member', 'admin')", name="ck_sso_connections_jit_role"),
    )


class SsoDomain(Base):
    __tablename__ = "sso_domains"

    domain: Mapped[str] = mapped_column(String(253), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dns_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        Index("ix_sso_domains_org", "organization_id"),
        CheckConstraint("domain = lower(domain)", name="ck_sso_domains_lower"),
    )


class SsoLoginRequest(Base):
    """One login in flight: the SAML AuthnRequest ID or the OIDC `state`.

    Used exactly once (`consumed_at`), within minutes (`expires_at`), and only by the browser that
    started it (`browser_hash` = SHA-256 of a cookie value). That is what makes `InResponseTo`
    checking (§4.2 step 2) stop replays and login CSRF.
    """

    __tablename__ = "sso_login_requests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    protocol: Mapped[str] = mapped_column(String(10), nullable=False)
    browser_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # OIDC only. Short-lived and single-use; the PKCE verifier must be sent back in clear.
    nonce: Mapped[str | None] = mapped_column(String(64), nullable=True)
    code_verifier: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 'login', or 'test': an org admin checking the connection with their own account. A test
    # never signs anyone in or provisions anyone; it only records the outcome.
    purpose: Mapped[str] = mapped_column(String(10), nullable=False, default="login")
    test_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        Index("ix_sso_login_requests_expires", "expires_at"),
        CheckConstraint("purpose IN ('login', 'test')", name="ck_sso_login_requests_purpose"),
    )
