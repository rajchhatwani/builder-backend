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
