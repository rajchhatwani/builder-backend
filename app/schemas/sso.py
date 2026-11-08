"""Request/response schemas for enterprise SSO (Phase D)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SsoConfigUpdate(BaseModel):
    """PUT /orgs/{slug}/sso. Fields of the other protocol are ignored and cleared.

    `oidc_client_secret` may be omitted on later saves to keep the stored one."""

    protocol: Literal["saml", "oidc"]
    idp_entity_id: str | None = Field(default=None, max_length=500)
    idp_sso_url: str | None = Field(default=None, max_length=500)
    idp_cert_pem: str | None = Field(default=None, max_length=20_000)
    oidc_discovery_url: str | None = Field(default=None, max_length=500)
    oidc_client_id: str | None = Field(default=None, max_length=255)
    oidc_client_secret: str | None = Field(default=None, max_length=2000)
    jit_enabled: bool = True
    jit_role: Literal["member", "admin"] = "member"
    # None keeps the stored value (false for a new connection).
    trust_unverified_email: bool | None = None


class SsoDomainCreate(BaseModel):
    domain: str = Field(min_length=1, max_length=260)


class SsoDomainRead(BaseModel):
    domain: str
    verified_at: datetime | None
    created_at: datetime
    dns_record_type: str = "TXT"
    dns_record_name: str
    dns_record_value: str


class SsoCertificateRead(BaseModel):
    sha256_fingerprint: str
    not_after: str
    subject: str


class SsoServiceProviderRead(BaseModel):
    """What the org admin pastes into their IdP."""

    entity_id: str
    acs_url: str
    metadata_url: str
    oidc_redirect_uri: str
    login_url: str


class SsoTestRead(BaseModel):
    """The last "test with my own e-mail" round trip (§12.D.6)."""

    at: datetime
    result: str  # 'ok' or the failure reason (same codes as `sso_error`, plus 'email_mismatch')
    tested_by_email: str | None = None


class SsoTestStart(BaseModel):
    """Open `login_url` in the browser (a full navigation, not fetch): it goes to the IdP and
    comes back to `#/org/<slug>/sso?sso_test=<result>` without signing anyone in."""

    login_url: str
    expires_in: int


class SsoCheckItemRead(BaseModel):
    name: str  # plan, verified_domain, configuration, active, certificate, client_secret,
    # discovery, jwks, last_test
    status: Literal["ok", "warning", "error"]
    detail: str | None = None


class SsoCheckRead(BaseModel):
    ok: bool
    protocol: str | None
    active: bool
    checks: list[SsoCheckItemRead]


class SsoConfigRead(BaseModel):
    configured: bool
    allowed_by_plan: bool
    protocol: str | None = None
    active: bool = False
    idp_entity_id: str | None = None
    idp_sso_url: str | None = None
    idp_certificate: SsoCertificateRead | None = None
    oidc_discovery_url: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret_set: bool = False
    jit_enabled: bool = True
    jit_role: str = "member"
    trust_unverified_email: bool = False
    updated_at: datetime | None = None
    last_test: SsoTestRead | None = None
    sp: SsoServiceProviderRead
    domains: list[SsoDomainRead]


class LoginDiscoverRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class LoginDiscoverRead(BaseModel):
    """`sso`: send the browser to `login_url`. `password`: show the password form."""

    method: Literal["sso", "password"]
    login_url: str | None = None
    organization_name: str | None = None
