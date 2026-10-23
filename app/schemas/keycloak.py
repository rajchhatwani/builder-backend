"""Pydantic schemas for a project's Keycloak settings (builder API layer).

Shapes and ranges are checked here; whether a combination is *legal* (https redirect URIs,
required provider fields, rejected auth features) is `validation.validate`'s job, so the
dashboard can save work in progress and see every problem in one report.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import AuthProvider, IdpType, KeycloakMode, MfaMode


class IdentityProvider(BaseModel):
    """One external login. The client secret is never stored: it is an environment variable
    (KC_IDP_<ALIAS>_CLIENT_SECRET) of the generated project."""

    alias: str = Field(min_length=1, max_length=31)
    type: IdpType
    display_name: str | None = Field(default=None, max_length=100)
    client_id: str = Field(min_length=1, max_length=255)
    tenant_id: str | None = Field(default=None, max_length=100)
    hosted_domain: str | None = Field(default=None, max_length=255)
    # Generic OIDC only: the endpoints from the provider's .well-known/openid-configuration.
    issuer: str | None = Field(default=None, max_length=2000)
    authorization_url: str | None = Field(default=None, max_length=2000)
    token_url: str | None = Field(default=None, max_length=2000)
    jwks_url: str | None = Field(default=None, max_length=2000)
    userinfo_url: str | None = Field(default=None, max_length=2000)


class KeycloakConfigWrite(BaseModel):
    """Body of PUT /projects/{id}/keycloak. Omitted ids default from the project slug."""

    mode: KeycloakMode = KeycloakMode.own
    realm: str | None = Field(default=None, min_length=1, max_length=63)
    api_client_id: str | None = Field(default=None, min_length=1, max_length=100)
    web_client_id: str | None = Field(default=None, min_length=1, max_length=100)
    redirect_uris: list[str] = Field(default_factory=list, max_length=20)
    password_min_length: int = Field(default=12, ge=1, le=512)
    mfa: MfaMode = MfaMode.optional
    session_idle_minutes: int = Field(default=30, ge=1, le=1_000_000)
    session_max_hours: int = Field(default=10, ge=1, le=100_000)
    audit_retention_days: int = Field(default=90, ge=1, le=100_000)
    identity_providers: list[IdentityProvider] = Field(default_factory=list, max_length=30)
    # Shared mode: the builder project whose Keycloak this one trusts.
    source_project_id: uuid.UUID | None = None


class KeycloakConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    # True when this project currently uses Keycloak (its auth provider is keycloak).
    active: bool = False
    mode: KeycloakMode
    realm: str
    api_client_id: str
    web_client_id: str
    redirect_uris: list[str]
    password_min_length: int
    mfa: MfaMode
    session_idle_minutes: int
    session_max_hours: int
    audit_retention_days: int
    identity_providers: list[IdentityProvider]
    source_project_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class KeycloakSwitchRequest(BaseModel):
    """Body of POST .../keycloak/enable and .../keycloak/disable: switching the identity
    provider is deliberate, so the caller must say so."""

    confirm: bool = False


class Dependent(BaseModel):
    id: uuid.UUID
    name: str


class KeycloakImpact(BaseModel):
    """What switching would change, shown before the user confirms."""

    action: str  # "enable" | "disable"
    provider: AuthProvider  # the current provider
    can_proceed: bool
    blockers: list[str]
    warnings: list[str]
    dependents: list[Dependent]
