"""Auth settings (generated).

Constants below were fixed when the project was generated. Secrets are read from the
environment (or .env) at first use and are never written into source.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = 'Notify Desk'

# Which identity provider this build uses (see app/auth/provider_lock.py).
PROVIDER = "builtin"
PROVIDER_REALM: str | None = None
# The "issuer" of this app's own tokens: how auth_identities tells them from a hub's.
ISSUER = 'builtin:notify-desk'


def current_issuer() -> str:
    return ISSUER
APP_URL = 'https://notify.example.com'

JWT_ALGORITHM = 'HS256'
TOKEN_STORE = 'db'
ACCESS_TOKEN_TTL_MINUTES = 15
REFRESH_TOKEN_TTL_DAYS = 7
OTP_TTL_MINUTES = 10
VERIFICATION_TTL_HOURS = 24
MAX_OTP_ATTEMPTS = 5

EMAIL_VERIFICATION_REQUIRED = False
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

LOGIN_RATE_LIMIT = '5/15minutes'
REGISTER_RATE_LIMIT = '10/hour'
RESET_RATE_LIMIT = '3/hour'

# Roles given to every new account, and each role's parent (a role holds its parent's rights).
DEFAULT_ROLES: tuple[str, ...] = ('member',)
# Roles a new user may pick for themselves when registering.
SELF_ASSIGNABLE_ROLES: tuple[str, ...] = ()
ROLE_PARENTS: dict[str, str | None] = {'admin': None, 'manager': 'member', 'member': None}

SMTP_HOST = 'smtp.example.com'
SMTP_PORT = 587
SMTP_USE_TLS = True
SMTP_FROM_EMAIL = 'noreply@orders.example.com'
SMTP_FROM_NAME = 'Order Desk'
SMS_PROVIDER: str | None = None


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Start once with this on to move a database to a different identity provider on purpose.
    auth_allow_provider_switch: bool = False

    # Signs access tokens. Generate one with: python -m app.auth.keys
    auth_jwt_secret: str = Field(min_length=32)

    @property
    def jwt_key(self) -> str:
        return self.auth_jwt_secret
    smtp_username: str | None = None
    smtp_password: str | None = None


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()  # type: ignore[call-arg]
