"""P4: refuse to start a deployed environment with a development-grade configuration.

Applies only when the environment was set explicitly and is not local/test. Messages name
settings, never values. The RLS requirement is not repeated here: `rls.startup_problem` owns it.
"""

import logging
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url

from app.config import Settings

log = logging.getLogger(__name__)
_LOOPBACK = {"localhost", "127.0.0.1", "::1", ""}


def production_problems(settings: Settings) -> list[str]:
    env = settings.environment
    if not settings.environment_explicit or env in ("local", "test"):
        return []
    out: list[str] = []
    if not settings.sandbox_runner_url or settings.sandbox_runner_token is None:
        out.append("BUILDER_SANDBOX_RUNNER_URL and BUILDER_SANDBOX_RUNNER_TOKEN")
    if settings.sandbox_runtime == "runc":
        out.append("BUILDER_SANDBOX_RUNTIME (runc is not an isolation boundary)")
    if not settings.preview_root:
        out.append("BUILDER_PREVIEW_ROOT")
    if not settings.preview_scheduler_enabled:
        out.append("BUILDER_PREVIEW_SCHEDULER_ENABLED=true")
    if settings.key_provider == "env":
        if settings.allow_env_key_provider:
            log.warning("env_key_provider_allowed: data-at-rest keys derive from SECRET_KEY")
        else:
            out.append("BUILDER_KEY_PROVIDER (file or command; or BUILDER_ALLOW_ENV_KEY_PROVIDER=true)")
    host = (urlsplit(settings.public_api_url).hostname or "").lower()
    if host in _LOOPBACK and not settings.mcp_allowed_hosts:
        out.append("BUILDER_PUBLIC_API_URL or BUILDER_MCP_ALLOWED_HOSTS (host allow-list)")
    try:
        url = make_url(settings.database_url)
        if (
            url.username == "builder"
            and (url.password or "") == "builder"
            and (url.host or "").lower() not in _LOOPBACK
        ):
            out.append("BUILDER_DATABASE_URL (development default credentials on a remote host)")
    except Exception:  # noqa: BLE001
        out.append("BUILDER_DATABASE_URL (unparseable)")
    return out


def check_production_ready(settings: Settings) -> None:
    problems = production_problems(settings)
    if problems:
        raise RuntimeError(
            f"environment {settings.environment!r} is not production-ready; missing or unsafe: "
            + "; ".join(problems)
        )
