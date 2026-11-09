from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", ".env.local"), env_prefix="BUILDER_", extra="ignore")

    # Default stays "local" for dev ergonomics, but isolation decisions use `environment_explicit`:
    # an UNSET environment never unlocks the runc fallback (S2-006).
    environment: str = "local"
    log_level: str = "INFO"
    # Owner role used only by Alembic and `python -m app.core.rls`. Unset = same as database_url.
    # In production database_url is the least-privilege API role (no superuser, no BYPASSRLS).
    migrations_database_url: str | None = None
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
    # Cap for spec writes (PUT /spec and the per-block PUTs), on the bytes actually received. 413 above it.
    max_spec_write_bytes: int = 1024 * 1024
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
    # CO3-7: how long an e-mail verification link works, and the wait between two resends.
    email_verification_hours: int = 24
    email_verification_resend_seconds: int = 60
    # Sign-up answers no faster than this, so a new address (org + token rows) and an existing
    # one (nothing to write) cost the caller the same time. Must exceed the slower branch.
    signup_response_floor_ms: int = 300
    # Phase C: signing secret(s) of the Stripe webhook endpoint (whsec_...). Comma-separate
    # two during a secret roll. Unset → POST /billing/stripe/webhook answers 503.
    stripe_webhook_secret: SecretStr | None = None
    # Deliveries signed longer ago than this are refused (replay protection).
    stripe_webhook_tolerance_seconds: int = 300

    # -- enterprise SSO (Phase D). The API's own public base URL: SAML entity IDs, the ACS URL
    # and the OIDC redirect URI are built from it, so it must be what the IdP can reach.
    public_api_url: str = "http://localhost:8000"
    # Extra Host header values the /mcp endpoint accepts besides public_api_url's host and
    # localhost (e.g. an internal service name). Anything else gets 421 (DNS-rebinding guard).
    mcp_allowed_hosts: list[str] = []
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

    # -- Phase F hardening. Impersonation (§4.5): how long a "view as" session lasts and how
    # long one explicit "allow writes" switch-on lasts (capped by the session itself).
    impersonation_minutes: int = 10
    impersonation_write_minutes: int = 5
    # Postgres row-level security (§3.3). Off by default. On = every org-scoped request binds
    # `SET LOCAL app.organization_id` on its transaction. The policies themselves are enabled
    # separately (`python -m app.rls enable`), so flipping this alone never changes visibility.
    rls_enabled: bool = False
    # P6: where data-at-rest keys come from. `env` derives key id env0 from SECRET_KEY (as before);
    # `file` / `command` read '<keyid> <base64 32-byte key>' lines (first = active) and then
    # SECRET_KEY is no longer a trust root for stored secrets. No cloud SDK: use a KMS CLI wrapper.
    key_provider: Literal["env", "file", "command"] = "env"
    key_provider_file: str | None = None
    key_provider_command: str | None = None
    # Extra env var NAMES (comma/space separated) passed to the key command besides PATH and HOME.
    key_provider_command_env: str = ""
    # P4: an explicit non-local/test environment refuses key_provider=env unless this is set.
    allow_env_key_provider: bool = False
    # Daily support-access digest (§4.5). Either or both; neither = "no destination".
    # The webhook is Slack-compatible (`{"text": …}`); its URL is a secret and is never logged.
    security_digest_webhook_url: SecretStr | None = None
    security_digest_email: str | None = None
    security_digest_hours: int = 24

    # -- AI model providers (B3-7). Keys are BYO per org (encrypted at rest), never in config.
    ai_provider: Literal["claude", "fake"] = "claude"
    ai_small_model: str = "claude-haiku-5-5"
    ai_large_model: str = "claude-sonnet-5-5"
    # Override or extend the price table: {"model": {"input": n, "output": n, "cache_read": n,
    # "cache_write": n}} in micro-USD per million tokens. Unknown model = refused, not free.
    ai_price_table: dict[str, dict[str, int]] = {}
    # Per-org monthly cap in micro-USD when the org set none. None = no cap.
    ai_default_monthly_budget_micro_usd: int | None = None
    ai_request_timeout_seconds: float = 120.0
    # A spend reservation not settled within this long is treated as orphaned (process died) and freed.
    # Keep it well above ai_request_timeout_seconds so a slow live call is never freed under it.
    ai_reservation_ttl_seconds: float = 900.0
    # The owner's own key (BUILDER_AI_API_KEY in the git-ignored .env.local). Used ONLY for orgs
    # whose ID (uuid string, never the slug: slugs are user-chosen) is listed in ai_platform_key_orgs and that have no key of their own; the
    # platform cap bounds the total spend either way.
    ai_api_key: SecretStr | None = None
    ai_platform_key_orgs: list[str] = []
    # Platform-wide, all-time hard cap on REAL model spend (micro-USD), all orgs, all callers.
    # Every call reserves its worst-case cost first and is refused if it could pass the cap.
    # Default 4.50 USD under a 5 USD console limit. Only a config change raises it; an admin can
    # only lower it (ai_platform_budget.cap_override_micro_usd). None = no platform cap.
    ai_platform_cap_micro_usd: int | None = 4_500_000
    # S2-008: this DATABASE's share of the console key's limit. Every stack/database has its own
    # counter, so N databases sharing one key would each allow the full cap; set this to the share
    # granted to this one (scripts/model_budget.sh keeps the shares under one console limit). The
    # effective cap is the minimum of this, ai_platform_cap_micro_usd and the admin override.
    ai_console_key_cap_micro_usd: int | None = None

    @property
    def sso_require_https(self) -> bool:
        return not self.sso_allow_http_idp

    def stripe_webhook_secrets(self) -> list[str]:
        if self.stripe_webhook_secret is None:
            return []
        raw = self.stripe_webhook_secret.get_secret_value()
        return [s.strip() for s in raw.split(",") if s.strip()]

    # -- sandbox + draft workspaces (B3-4). Generated/AI-written code only ever runs in a sandbox.
    # OCI runtime for every sandbox. Fails closed if it is not registered with Docker; `runc`
    # (no user-space kernel) is accepted only when environment is local/test.
    sandbox_runtime: str = "runsc"
    sandbox_docker_bin: str = "docker"
    # P1 narrow runner. API side: when `sandbox_runner_url` is set (http://127.0.0.1:PORT or
    # unix:///path.sock, https:// for a remote one) every sandbox call goes to the runner and the
    # API process never runs the docker binary. The token is mandatory with it.
    sandbox_runner_url: str | None = None
    sandbox_runner_token: SecretStr | None = None
    # Runner side: the only directory a code mount may come from (== preview_root/workspace_root).
    runner_mount_root: str | None = None
    # Root of per-project git repos + worktrees. Unset -> workspaces answer 503.
    workspace_root: str | None = None
    # Postgres server (admin URL, needs CREATEDB) hosting preview DBs. Unset -> workspaces 503.
    workspace_db_admin_url: SecretStr | None = None
    # Optional template database the preview DB is cloned from (synthetic data). Empty DB if unset.
    workspace_template_db: str | None = None
    # Images a sandbox may run (exact refs; pin by digest in production). Never pulled: the
    # image must already exist on the runner (`--pull never`).
    sandbox_images: list[str] = ["python:3.12-slim", "postgres:16-alpine", "bb-preview-app:1"]
    # How often the preview runtime should call reap_expired() (no scheduler lives here yet).
    sandbox_reap_interval_seconds: int = 60
    workspace_max_active_per_project: int = 5
    workspace_max_checkpoints: int = 20
    # Per workspace: preview DB size (checked before every checkpoint) and worktree size.
    workspace_max_db_bytes: int = 1024**3
    workspace_max_disk_bytes: int = 200 * 1024**2

    # -- preview runtime (B3-10). Unset preview_root -> previews answer 503.
    # Where each preview's generated code lives (read-only mount into its sandbox).
    preview_root: str | None = None
    # Prebuilt image holding the generated project's runtime dependencies (never pulled).
    preview_app_image: str = "bb-preview-app:1"
    preview_db_image: str = "postgres:16-alpine"
    # App-startup scheduler for the idle-sleep / expiry sweep + reaper. Off unless enabled.
    preview_scheduler_enabled: bool = False
    # Agent runs: live runs per project (S1-006) and the crash-resume sweeper (B-003). The sweeper
    # re-drives runs whose lease expired; it is never started when environment == "test".
    agent_max_live_runs_per_project: int = 5
    agent_sweeper_enabled: bool = True
    agent_sweep_interval_seconds: int = 30
    agent_sweep_max_runs: int = 3
    agent_max_recoveries: int = 3
    # Approval policy (B-001). Platform values; an org may only TIGHTEN them (ai_org_settings.approval_policy).
    # Lifetimes in hours (clamped 1 min .. 7 days); roles kind->"owner" can only RAISE the built-in floor;
    # auto-approval of a small plan edit is off; separation of duties (the run's creator may not approve
    # their own run) is off, an org owner can switch it on.
    ai_approval_ttl_hours: int = 24
    ai_approval_ttl_plan_hours: int = 168
    ai_approval_roles: dict[str, str] = {}
    ai_approval_auto_plan_small_edit: bool = False
    ai_approval_separation_of_duties: bool = False
    # Dependency approvals (B3-9) expire so a package is re-vetted periodically.
    dependency_approval_ttl_days: int = 90
    preview_sweep_interval_seconds: int = 60
    # With the scheduler off, preview API calls start a sweep (at most once per interval).
    preview_lazy_sweep: bool = True
    preview_wake_timeout_seconds: int = 90
    preview_ip_rate_per_minute: int = 600  # S2-005: pre-auth, per client address, per process
    preview_max_body_bytes: int = 1024**2
    preview_max_response_bytes: int = 8 * 1024**2
    preview_request_timeout_seconds: int = 30
    preview_log_stream_max_seconds: int = 60

    @model_validator(mode="after")
    def _runner_settings_fail_closed(self) -> "Settings":
        url = self.sandbox_runner_url
        if url is None:
            return self
        token = self.sandbox_runner_token
        if token is None or len(token.get_secret_value()) < 32:
            raise ValueError("sandbox_runner_url requires sandbox_runner_token (>= 32 chars)")
        from urllib.parse import urlsplit

        parts = urlsplit(url)
        loopback = parts.hostname in ("127.0.0.1", "::1", "localhost")
        ok = (
            (parts.scheme == "unix" and parts.path.startswith("/"))
            or (parts.scheme == "http" and loopback)
            or (parts.scheme == "https" and bool(parts.hostname))
        )
        if not ok:
            raise ValueError(
                "sandbox_runner_url must be unix:///path, http://127.0.0.1:port or https://host"
            )
        return self

    @property
    def environment_explicit(self) -> bool:
        """True only when the environment was actually provided (env var, .env or constructor)."""
        return "environment" in self.model_fields_set

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
