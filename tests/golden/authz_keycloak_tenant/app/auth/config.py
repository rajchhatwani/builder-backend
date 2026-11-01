"""Auth settings for Keycloak sign-in (generated).

Constants below were fixed when the project was generated. Where Keycloak lives is read from
the environment, so the same build runs against any environment. There are no secrets here:
this service only verifies tokens, it never holds a client secret.
"""

import uuid
from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = 'Crm'

PROVIDER = "keycloak"
PROVIDER_REALM: str | None = 'crm'
REALM = 'crm'
# Tokens must be issued for this client (the `aud` claim) to be accepted.
API_CLIENT_ID = 'crm-api'
# The public client browsers sign in with, and the one Swagger UI (/docs) uses.
WEB_CLIENT_ID = 'crm-web'
DOCS_CLIENT_ID = 'crm-web-docs'

EMAIL_VERIFICATION_REQUIRED = False
SECURITY_HEADERS_ENABLED = True

# Roles every signed-in user holds, and each role's parent (a role holds its parent's rights).
DEFAULT_ROLES: tuple[str, ...] = ('member',)
SELF_ASSIGNABLE_ROLES: tuple[str, ...] = ()
ROLE_PARENTS: dict[str, str | None] = {'admin': None, 'member': None}

# Each Keycloak organization is a tenant. Its id is derived from the organization's alias under
# this fixed namespace (not from the Keycloak address), so it never changes between environments.
MULTI_TENANT = True
TENANT_NAMESPACE = uuid.UUID('eff75b8e-eb21-54d4-aa58-ad3f39bec7f0')

# Custom registration fields: (name, type, max length, allowed values, default). Keycloak keeps and
# validates them; each reaches the API as a claim of the same name and is copied to auth_users.
CUSTOM_FIELDS: tuple[tuple[str, str, int | None, tuple[str, ...], str | None], ...] = (
    (
        'age',
        'integer',
        None,
        (),
        None,
    ),
    (
        'born',
        'date',
        None,
        (),
        None,
    ),
    (
        'company',
        'string',
        80,
        (),
        None,
    ),
    (
        'mobile',
        'phone',
        None,
        (),
        None,
    ),
    (
        'newsletter',
        'boolean',
        None,
        (),
        None,
    ),
    (
        'notes',
        'text',
        None,
        (),
        None,
    ),
    (
        'plan',
        'enum',
        None,
        ("free", "pro"),
        'free',
    ),
    (
        'score',
        'float',
        None,
        (),
        None,
    ),
    (
        'site',
        'url',
        None,
        (),
        None,
    ),
)

# Signing keys are fetched from Keycloak and cached.
JWKS_TTL_SECONDS = 600
# At most one refetch this often, however many unknown key ids arrive (no amplification).
JWKS_MIN_REFETCH_SECONDS = 30
# If Keycloak is unreachable, cached keys keep working this long past their TTL; then fail closed.
JWKS_MAX_STALE_SECONDS = 3600
JWKS_TIMEOUT_SECONDS = 3
JWKS_MAX_BYTES = 65536
CLOCK_LEEWAY_SECONDS = 30
MAX_TOKEN_BYTES = 8192


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Where people reach Keycloak, e.g. https://id.example.com (no realm path, no trailing slash).
    # Tokens are only accepted when their issuer is exactly this URL plus /realms/<realm>.
    keycloak_public_url: str = Field(min_length=8)
    # Optional address this service uses to fetch keys when it cannot reach the public one
    # (for example http://keycloak:8080 inside docker compose).
    keycloak_internal_url: str | None = None
    # "production" refuses a plain http issuer.
    app_env: str = "development"
    # Start once with this on to move a database to a different identity provider on purpose.
    auth_allow_provider_switch: bool = False
    # Keycloak's "backchannel logout URL" calls POST /auth/backchannel-logout. Off until you
    # point Keycloak at it: a signed logout token from your realm then ends that session here.
    auth_backchannel_logout_enabled: bool = False

    @field_validator("keycloak_public_url", "keycloak_internal_url")
    @classmethod
    def clean_url(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        value = value.strip().rstrip("/")
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("must be an http(s) URL such as https://id.example.com")
        if parts.query or parts.fragment or parts.username or parts.password:
            raise ValueError("must not contain a query, fragment or credentials")
        return value

    @model_validator(mode="after")
    def production_needs_https(self) -> "AuthSettings":
        if self.app_env.lower() == "production" and not self.keycloak_public_url.startswith(
            "https://"
        ):
            raise ValueError(
                "KEYCLOAK_PUBLIC_URL must be https when APP_ENV=production "
                "(terminate TLS in front of Keycloak)"
            )
        return self

    @property
    def issuer(self) -> str:
        return f"{self.keycloak_public_url}/realms/{REALM}"

    @property
    def jwks_url(self) -> str:
        base = self.keycloak_internal_url or self.keycloak_public_url
        return f"{base}/realms/{REALM}/protocol/openid-connect/certs"


def current_issuer() -> str:
    return get_auth_settings().issuer


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()  # type: ignore[call-arg]
