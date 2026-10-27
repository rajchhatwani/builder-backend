from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="BUILDER_", extra="ignore")

    environment: str = "local"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://builder:builder@localhost:5432/builder"
    cors_origins: list[str] = ["http://localhost:5173"]

    # -- accounts (WP1). SECRET_KEY itself is read from the environment by app.core.* --
    # open: anyone can create a customer account. closed: only an administrator can.
    signup_mode: Literal["open", "closed"] = "open"
    # Created once at startup when the platform has no administrator yet. Never logged.
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: SecretStr | None = None
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    admin_refresh_token_hours: int = 12  # administrators re-authenticate more often
    login_max_failures: int = 5
    lockout_minutes: int = 15
    # Per client IP, per window, across login / register / refresh. In-process (per worker).
    auth_rate_limit_attempts: int = 30
    auth_rate_limit_window_seconds: int = 300
    # Only turn on behind a proxy that overwrites X-Forwarded-For; otherwise clients can spoof it.
    trust_proxy_headers: bool = False
    max_request_bytes: int = 10 * 1024 * 1024
    # /docs and /openapi.json: on in `local`, off elsewhere unless asked for.
    enable_docs: bool | None = None

    # -- billing (Platform SaaS Phase B: Checkout only; webhooks arrive in Phase C) --
    # Unset → checkout answers 503 and the UI hides the upgrade button.
    stripe_secret_key: SecretStr | None = None
    # plan id → Stripe Price id, e.g. BUILDER_STRIPE_PRICE_IDS='{"team":"price_..."}'.
    # Kept in config, not in `plans`, so the §3 schema stays as designed.
    stripe_price_ids: dict[str, str] = {}
    # Where the browser app lives; Checkout returns the customer here.
    public_app_url: str = "http://localhost:5173"

    # Days between an owner's deletion request and the deletion itself. Access is blocked
    # meanwhile; the owner can revoke. An operator can set another period per org.
    org_deletion_grace_days: int = 7

    # -- platform e-mail (org invitations). Unset host → invites aren't e-mailed; the admin
    # copies the link from the UI instead. Never logged.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str = "Backend Builder <no-reply@localhost>"
    smtp_starttls: bool = True
    # Phase C: signing secret(s) of the Stripe webhook endpoint (whsec_...). Comma-separate
    # two during a secret roll. Unset → POST /billing/stripe/webhook answers 503.
    stripe_webhook_secret: SecretStr | None = None
    # Deliveries signed longer ago than this are refused (replay protection).
    stripe_webhook_tolerance_seconds: int = 300

    # -- enterprise SSO (Phase D). The API's own public base URL: SAML entity IDs, the ACS URL
    # and the OIDC redirect URI are built from it, so it must be what the IdP can reach.
    public_api_url: str = "http://localhost:8000"
    # Let org admins point OIDC at hosts on private networks (a self-hosted IdP inside the
    # same VPC). Off: such URLs are refused, which is what stops SSRF through the config form.
    sso_allow_private_idp: bool = False
    # Allow plain-http IdP URLs (a local Keycloak on a laptop). Never in production.
    sso_allow_http_idp: bool = False
    # How long a started SSO login may take at the IdP before it has to be restarted.
    sso_login_ttl_seconds: int = 600

    # -- MFA (§4.4 Phase 1). Platform staff must use TOTP at every sign-in (admin console and
    # customer app); turning this off is for local development only.
    admin_mfa_required: bool = True
    # How long the "enter your code" step may take after the password was accepted.
    mfa_challenge_seconds: int = 300
    # The name authenticator apps show next to the account.
    totp_issuer: str = "Builder"

    @property
    def sso_require_https(self) -> bool:
        return not self.sso_allow_http_idp

    def stripe_webhook_secrets(self) -> list[str]:
        if self.stripe_webhook_secret is None:
            return []
        raw = self.stripe_webhook_secret.get_secret_value()
        return [s.strip() for s in raw.split(",") if s.strip()]

    @property
    def is_local(self) -> bool:
        return self.environment == "local"

    @property
    def docs_enabled(self) -> bool:
        return self.is_local if self.enable_docs is None else self.enable_docs

    @property
    def cookie_secure(self) -> bool:
        return not self.is_local


@lru_cache
def get_settings() -> Settings:
    return Settings()
