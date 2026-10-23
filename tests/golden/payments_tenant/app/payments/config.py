"""Payments settings (generated).

The constants below come from the project's spec. Secrets never do: provider keys and webhook
secrets are read from the environment (or from files named by NAME_FILE variables, which is how
Docker and Kubernetes secrets arrive) and are held as SecretStr so they never show in a repr.
"""

import ipaddress
import os
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.redact import register_secret

PROVIDER = 'stripe'
MULTI_TENANT = True
CURRENCIES: tuple[str, ...] = ("USD", "EUR", "JPY")
# decimals of the minor unit, per allowed currency (0 = no minor unit, 2 = cents)
EXPONENTS: dict[str, int] = {'EUR': 2, 'JPY': 0, 'USD': 2}
MAX_AMOUNT_MINOR = 5000000
SUCCESS_URLS: tuple[str, ...] = ("https://shop.example.com/paid",)
CANCEL_URLS: tuple[str, ...] = ("https://shop.example.com/cart",)
# None means no refund needs a second person
REFUND_APPROVAL_THRESHOLD_MINOR: int | None = None

# Who may do what. An empty tuple means nobody: the routes fail closed.
ROLES: dict[str, tuple[str, ...]] = {
    'create': ("member",),
    'read': ("member",),
    'read_all': ("manager", "admin"),
    'refund': ("manager",),
    'approve_refund': (),
    'operate': ("admin",),
}

# Security knobs, fixed when the project was generated (the spec enforces floors and ceilings).
WEBHOOK_TOLERANCE_SECONDS = 120
WEBHOOK_MAX_BODY_BYTES = 262144
WEBHOOK_IP_ALLOWLIST_ENABLED = True
IDEMPOTENCY_TTL_HOURS = 48
AUDIT_RETENTION_DAYS = 2555
SECRETS_FROM_FILES = True

# Deployment sizing computed from the expected load when the project was generated. Every value
# can be overridden by the environment variable of the same name in upper case (see DEPLOYMENT.md).
SIZING_WEBHOOK_MODE = 'queued'
SIZING_WORKER_CONCURRENCY = 8
SIZING_POLL_INTERVAL_SECONDS = 0.2
SIZING_WEBHOOK_EVENTS_RETENTION_DAYS = 90
SIZING_JOBS_RETENTION_DAYS = 30

_SECRET_NAMES = ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRETS")
_KEY_PREFIXES = ("sk_live_", "sk_test_", "rk_live_", "rk_test_")
_LIVE_PREFIXES = ("sk_live_", "rk_live_")
_API_BASE = "https://api.stripe.com"


class PaymentsConfigError(RuntimeError):
    """The payments settings are missing or unsafe: the app refuses to start."""


class PaymentsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    stripe_secret_key: SecretStr | None = None
    # one or more signing secrets, comma separated: a second one makes secret rotation seamless
    stripe_webhook_secrets: SecretStr | None = None
    # Only for tests and local mocks; production always talks to Stripe itself.
    stripe_api_base: str = _API_BASE
    # inline: processed inside the webhook request. queued: stored, then handled by workers.
    payments_webhook_mode: str = SIZING_WEBHOOK_MODE
    # Comma-separated CIDRs the webhook may be called from (used when the spec enabled the allowlist).
    payments_webhook_ip_allowlist: str = ""
    # Number of reverse proxies in front of the API whose X-Forwarded-For is trusted (0 = none).
    payments_trusted_proxies: int = 0
    payments_allow_mode_switch: bool = False
    payments_worker_concurrency: int = SIZING_WORKER_CONCURRENCY
    payments_poll_interval_seconds: float = SIZING_POLL_INTERVAL_SECONDS
    payments_scheduler: bool = True
    payments_job_lease_seconds: int = 120
    payments_job_max_attempts: int = 8
    payments_webhook_events_retention_days: int = SIZING_WEBHOOK_EVENTS_RETENTION_DAYS
    payments_jobs_retention_days: int = SIZING_JOBS_RETENTION_DAYS
    payments_provider_timeout_seconds: float = 10.0

    @property
    def production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def api_base(self) -> str:
        return self.stripe_api_base

    @property
    def livemode(self) -> bool:
        """Test or live, decided by the shape of the API key and nothing else."""
        return self.public_key().startswith(_LIVE_PREFIXES)

    def public_key(self) -> str:
        """The part of the credentials that names the mode (Razorpay's key id, Stripe's key)."""
        return self.secret_key()

    def secret_key(self) -> str:
        if self.stripe_secret_key is None:
            raise PaymentsConfigError("STRIPE_SECRET_KEY is not set")
        return self.stripe_secret_key.get_secret_value()

    def webhook_secrets(self) -> list[str]:
        secrets = self.stripe_webhook_secrets
        if secrets is None:
            return []
        return [s.strip() for s in secrets.get_secret_value().split(",") if s.strip()]

    def webhook_networks(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        return [
            ipaddress.ip_network(part.strip(), strict=False)
            for part in self.payments_webhook_ip_allowlist.split(",")
            if part.strip()
        ]

    def check(self) -> None:
        """Refuse unsafe or incomplete settings. Called at start-up (API and worker)."""
        public = self.public_key()
        secret = self.secret_key()
        if not public.startswith(_KEY_PREFIXES) or len(secret) < 20:
            raise PaymentsConfigError("STRIPE_SECRET_KEY does not look like a Stripe API key")
        if self.production and not self.livemode:
            raise PaymentsConfigError(
                "APP_ENV=production needs live keys, not test keys"
            )
        if self.livemode and not self.production:
            raise PaymentsConfigError(
                "a live key is only accepted when APP_ENV=production, so test machines can never "
                "move real money"
            )
        secrets = self.webhook_secrets()
        if not secrets:
            raise PaymentsConfigError("STRIPE_WEBHOOK_SECRETS is not set")
        if any(not s.startswith("whsec_") or len(s) < 16 for s in secrets):
            raise PaymentsConfigError("STRIPE_WEBHOOK_SECRETS must be whsec_... signing secrets")
        if self.production and self.api_base != _API_BASE:
            raise PaymentsConfigError("STRIPE_API_BASE may only be changed outside production")
        if not self.production and self.api_base != _API_BASE:
            host = self.api_base.split("//", 1)[-1].split("/", 1)[0].split(":")[0]
            if not self.api_base.startswith(("http://", "https://")) or not host:
                raise PaymentsConfigError("STRIPE_API_BASE must be an http(s) URL")
        if self.payments_webhook_mode not in ("inline", "queued"):
            raise PaymentsConfigError("PAYMENTS_WEBHOOK_MODE must be inline or queued")
        if WEBHOOK_IP_ALLOWLIST_ENABLED and not self.webhook_networks():
            raise PaymentsConfigError(
                "the webhook IP allowlist is on but PAYMENTS_WEBHOOK_IP_ALLOWLIST is empty"
            )
        if not 1 <= self.payments_worker_concurrency <= 256:
            raise PaymentsConfigError("PAYMENTS_WORKER_CONCURRENCY must be between 1 and 256")
        if not 0.05 <= self.payments_poll_interval_seconds <= 60:
            raise PaymentsConfigError("PAYMENTS_POLL_INTERVAL_SECONDS must be between 0.05 and 60")


def _secrets_from_files() -> dict[str, SecretStr]:
    """NAME_FILE=/run/secrets/x supplies NAME. Setting both is ambiguous, so it is refused."""
    found: dict[str, SecretStr] = {}
    if not SECRETS_FROM_FILES:
        return found
    for name in _SECRET_NAMES:
        path = os.environ.get(f"{name}_FILE")
        if not path:
            continue
        if os.environ.get(name):
            raise PaymentsConfigError(f"set either {name} or {name}_FILE, not both")
        try:
            value = Path(path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise PaymentsConfigError(f"cannot read the file named by {name}_FILE") from exc
        found[name.lower()] = SecretStr(value)
    return found


@lru_cache
def get_payments_settings() -> PaymentsSettings:
    # Constructor arguments win over the environment, which is what lets a file-based secret apply.
    settings = PaymentsSettings(**_secrets_from_files())  # type: ignore[arg-type]
    # Whatever the secrets look like, they must never reach a log line or an audit record.
    for secret in (*settings.webhook_secrets(), *([settings.secret_key()] if _has_key(settings) else [])):
        register_secret(secret)
    return settings


def _has_key(settings: PaymentsSettings) -> bool:
    try:
        settings.secret_key()
    except PaymentsConfigError:
        return False
    return True
