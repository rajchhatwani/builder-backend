"""The SPEC: the contract between the builder API and the generator (PLAN.md section 3).

Deliberately lenient about *values* (plain `str` for names and enum-like fields, no
patterns or length limits). Rejecting bad values is `validation.validate`'s job, so one
call can report every issue instead of stopping at the first Pydantic error. Structure
is strict (`extra="forbid"`, correct JSON types) so nothing is silently dropped on import.

Relations reference entities by *name*, not id, so a spec is portable between projects.
Field order is the list order (no `position`); entities and relations are emitted sorted
so the same model always serializes to the same spec.
"""

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SPEC_VERSION = 1
ALLOWED_OPERATIONS = frozenset({"list", "get", "create", "replace", "update", "delete", "head"})


class _SpecModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpecProject(_SpecModel):
    name: str
    slug: str
    description: str | None = None
    db_engine: str = "postgres"


class SpecEntityOptions(_SpecModel):
    operations: list[str] = Field(default_factory=lambda: sorted(ALLOWED_OPERATIONS))
    filterable: list[str] = Field(default_factory=list)
    sortable: list[str] = Field(default_factory=list)
    searchable: list[str] = Field(default_factory=list)
    default_page_size: int = 20
    max_page_size: int = 100
    soft_delete: bool = False


class SpecField(_SpecModel):
    name: str
    type: str
    required: bool = False
    unique: bool = False
    indexed: bool = False
    default: Any | None = None
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    enum_values: list[str] | None = None


class SpecEntity(_SpecModel):
    name: str
    table_name: str
    plural_path: str
    options: SpecEntityOptions = Field(default_factory=SpecEntityOptions)
    fields: list[SpecField] = Field(default_factory=list)


class SpecRelation(_SpecModel):
    kind: str
    from_entity: str
    to_entity: str
    from_name: str
    to_name: str
    on_delete: str = "restrict"
    required: bool = False


class SpecSmtpConfig(_SpecModel):
    host: str
    port: int = 587
    use_tls: bool = True
    from_email: str
    from_name: str


class SpecSmsConfig(_SpecModel):
    from_number: str


class SpecAuthCustomField(_SpecModel):
    name: str
    label: str
    type: str  # AuthCustomFieldType value; validation module checks legality
    required: bool = False
    unique: bool = False
    indexed: bool = False
    min_length: int | None = None
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    default_value: str | None = None
    enum_values: list[str] | None = None


class SpecRole(_SpecModel):
    name: str
    label: str
    is_default: bool = False
    self_assignable: bool = False
    invite_only: bool = False
    inherits_from: str | None = None


class SpecPermission(_SpecModel):
    entity: str  # entity name (not id) for portability
    operation: str  # AuthOperation value; validation module checks legality
    roles: list[str] = Field(default_factory=list)
    row_rule: str | None = None  # RowRule value or None
    custom_filter_field: str | None = None
    custom_filter_value: str | None = None


class SpecPasswordReset(_SpecModel):
    email_magic_link: bool = True
    sms_otp: bool = False
    otp_ttl_minutes: int = 10


class SpecRegistration(_SpecModel):
    email_verification_required: bool = True
    invite_only: bool = False
    custom_fields: list[SpecAuthCustomField] = Field(default_factory=list)


class SpecAuthSecrets(_SpecModel):
    """Decrypted credentials injected at generation time.

    This model is NEVER serialised in HTTP responses.  It is populated
    by the generation service after calling AuthSecretsService.get_for_generator()
    and exists solely so Jinja templates can reference credentials by name.
    """

    smtp_username: str | None = None
    smtp_password: str | None = None
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    vonage_api_key: str | None = None
    vonage_api_secret: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region: str | None = None


class SpecIdentityProvider(_SpecModel):
    """One external login offered by the Keycloak realm. The client secret is never part of
    the spec: the generated project reads it from KC_IDP_<ALIAS>_CLIENT_SECRET."""

    alias: str
    type: str  # IdpType value; validation module checks legality
    display_name: str | None = None
    client_id: str
    tenant_id: str | None = None  # microsoft only: the Entra tenant (a GUID)
    hosted_domain: str | None = None  # google only: restrict sign-in to one Workspace domain
    # oidc only: the provider's endpoints, as listed in its .well-known/openid-configuration
    issuer: str | None = None
    authorization_url: str | None = None
    token_url: str | None = None
    jwks_url: str | None = None
    userinfo_url: str | None = None  # optional


class SpecKeycloak(_SpecModel):
    mode: str = "own"  # KeycloakMode value
    realm: str
    api_client_id: str
    web_client_id: str
    redirect_uris: list[str] = Field(default_factory=list)
    password_min_length: int = 12
    mfa: str = "optional"  # MfaMode value
    session_idle_minutes: int = 30
    session_max_hours: int = 10
    audit_retention_days: int = 90
    identity_providers: list[SpecIdentityProvider] = Field(default_factory=list)


class SpecAuth(_SpecModel):
    enabled: bool = True
    # Who manages users and tokens. The keycloak block is kept while the provider is builtin,
    # so switching back and forth does not lose the settings.
    provider: str = "builtin"  # AuthProvider value
    keycloak: SpecKeycloak | None = None
    token_store: str = "db"                     # TokenStore value
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7
    jwt_algorithm: str = "HS256"                # JwtAlgorithm value
    deletion_mode: str = "soft"                 # DeletionMode value
    multi_tenant: bool = False
    security_headers_enabled: bool = True
    app_name: str | None = None
    app_url: str | None = None
    password_reset: SpecPasswordReset = Field(default_factory=SpecPasswordReset)
    registration: SpecRegistration = Field(default_factory=SpecRegistration)
    smtp: SpecSmtpConfig | None = None
    sms_provider: str | None = None             # SmsProvider value
    sms: SpecSmsConfig | None = None
    login_rate_limit: str = "5/15minutes"
    register_rate_limit: str = "10/hour"
    reset_rate_limit: str = "3/hour"
    roles: list[SpecRole] = Field(default_factory=list)
    permissions: list[SpecPermission] = Field(default_factory=list)
    # Populated at generation time only — excluded from JSON output
    secrets: SpecAuthSecrets = Field(
        default_factory=SpecAuthSecrets, exclude=True
    )



class Spec(_SpecModel):
    spec_version: int = SPEC_VERSION
    project: SpecProject
    entities: list[SpecEntity] = Field(default_factory=list)
    relations: list[SpecRelation] = Field(default_factory=list)
    # Phase 2 hooks (PLAN.md section 13): accepted by the schema, rejected by validation
    # while non-empty, because nothing stores or generates them yet.
    features: list[str] = Field(default_factory=list)
    auth: SpecAuth | None = None


def spec_hash(spec: Spec) -> str:
    """Stable SHA-256 of the spec's canonical JSON; identical specs hash identically."""
    canonical = json.dumps(
        spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()
