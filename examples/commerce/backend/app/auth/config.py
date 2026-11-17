"""Auth settings (generated).

Constants below were fixed when the project was generated. Secrets are read from the
environment (or .env) at first use and are never written into source.
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = 'Commerce'

# Which identity provider this build uses (see app/auth/provider_lock.py).
PROVIDER = "builtin"
PROVIDER_REALM: str | None = None
APP_URL = 'http://localhost:3000'

JWT_ALGORITHM = 'RS256'
TOKEN_STORE = 'redis'
ACCESS_TOKEN_TTL_MINUTES = 30
REFRESH_TOKEN_TTL_DAYS = 14
OTP_TTL_MINUTES = 10
VERIFICATION_TTL_HOURS = 24
MAX_OTP_ATTEMPTS = 5

EMAIL_VERIFICATION_REQUIRED = True
EMAIL_MAGIC_LINK_ENABLED = False
SMS_OTP_ENABLED = False
HARD_DELETE = False
SECURITY_HEADERS_ENABLED = True
INVITE_ONLY = False
MULTI_TENANT = True
# The role the user who creates a tenant starts with.
ADMIN_ROLE = 'admin'
INVITATIONS_ENABLED = True
INVITATION_TTL_DAYS = 7

LOGIN_RATE_LIMIT = '600/minute'
REGISTER_RATE_LIMIT = '600/minute'
RESET_RATE_LIMIT = '600/minute'

# Roles given to every new account, and each role's parent (a role holds its parent's rights).
DEFAULT_ROLES: tuple[str, ...] = ('customer',)
# Roles a new user may pick for themselves when registering.
SELF_ASSIGNABLE_ROLES: tuple[str, ...] = ()
ROLE_PARENTS: dict[str, str | None] = {'admin': 'manager', 'catalog': None, 'customer': None, 'fulfillment': None, 'manager': None, 'marketing': None, 'support': None}

SMTP_HOST = 'host.docker.internal'
SMTP_PORT = 1025
SMTP_USE_TLS = False
SMTP_FROM_EMAIL = 'store@example.com'
SMTP_FROM_NAME = 'Commerce'
SMS_PROVIDER: str | None = None


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Start once with this on to move a database to a different identity provider on purpose.
    auth_allow_provider_switch: bool = False

    # RSA private key (PEM) that signs access tokens. Generate one with: python -m app.auth.keys
    # In a .env file or compose, write the newlines as \n inside double quotes.
    auth_jwt_private_key: str = Field(min_length=200)

    @field_validator("auth_jwt_private_key")
    @classmethod
    def unescape_newlines(cls, value: str) -> str:
        return value.replace("\\n", "\n")

    @property
    def jwt_key(self) -> str:
        return self.auth_jwt_private_key
    # Where refresh tokens are kept.
    redis_url: str = "redis://localhost:6379/0"
    smtp_username: str | None = None
    smtp_password: str | None = None


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()  # type: ignore[call-arg]
