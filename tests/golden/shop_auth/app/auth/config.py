"""Auth settings (generated).

Constants below were fixed when the project was generated. Secrets are read from the
environment (or .env) at first use and are never written into source.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = 'Shop'
APP_URL = 'https://shop.example.com'

JWT_ALGORITHM = 'HS256'
TOKEN_STORE = 'db'
ACCESS_TOKEN_TTL_MINUTES = 15
REFRESH_TOKEN_TTL_DAYS = 7
OTP_TTL_MINUTES = 10
VERIFICATION_TTL_HOURS = 24
MAX_OTP_ATTEMPTS = 5

EMAIL_VERIFICATION_REQUIRED = True
EMAIL_MAGIC_LINK_ENABLED = True
SMS_OTP_ENABLED = True
HARD_DELETE = False
SECURITY_HEADERS_ENABLED = True
INVITE_ONLY = False
MULTI_TENANT = False
# The role the user who creates a tenant starts with.
ADMIN_ROLE = 'admin'
INVITATIONS_ENABLED = False
INVITATION_TTL_DAYS = 7

LOGIN_RATE_LIMIT = '5/15minutes'
REGISTER_RATE_LIMIT = '10/hour'
RESET_RATE_LIMIT = '3/hour'

# Roles given to every new account, and each role's parent (a role holds its parent's rights).
DEFAULT_ROLES: tuple[str, ...] = ('customer',)
# Roles a new user may pick for themselves when registering.
SELF_ASSIGNABLE_ROLES: tuple[str, ...] = ()
ROLE_PARENTS: dict[str, str | None] = {'admin': None, 'customer': None, 'staff': 'admin'}

SMTP_HOST = 'smtp.example.com'
SMTP_PORT = 587
SMTP_USE_TLS = True
SMTP_FROM_EMAIL = 'noreply@shop.example.com'
SMTP_FROM_NAME = 'Shop'
SMS_PROVIDER = 'twilio'
SMS_FROM = '+14155550100'


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Signs access tokens. Generate one with: python -m app.auth.keys
    auth_jwt_secret: str = Field(min_length=32)

    @property
    def jwt_key(self) -> str:
        return self.auth_jwt_secret
    smtp_username: str | None = None
    smtp_password: str | None = None
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()  # type: ignore[call-arg]
