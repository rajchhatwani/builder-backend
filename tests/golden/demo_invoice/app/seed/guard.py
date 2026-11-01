"""Production guard (generated). Seed data is for development and demos only.

Seeding and resetting refuse to run unless APP_ENV (and ENVIRONMENT, when set) names a development-like
environment. A missing value, `production`, `staging` or any name not on the list is refused. Overriding
needs BOTH the `--allow-production` flag AND the environment variable SEED_ALLOW_PRODUCTION=yes.
"""

import os
from collections.abc import Mapping

SAFE_ENVIRONMENTS = frozenset({"local", "dev", "development", "test", "testing", "demo", "preview"})
ENV_NAMES = ("APP_ENV", "ENVIRONMENT")
OVERRIDE_ENV = "SEED_ALLOW_PRODUCTION"
OVERRIDE_VALUE = "yes"


class SeedRefused(Exception):
    """The environment is not a development one (or the override is incomplete)."""


def problems(env: Mapping[str, str]) -> list[str]:
    found = [(name, env[name].strip().lower()) for name in ENV_NAMES if env.get(name, "").strip()]
    if not found:
        return ["APP_ENV is not set, so the environment is unknown (set APP_ENV=development)"]
    return [
        f"{name}={value!r} is not a development environment" for name, value in found
        if value not in SAFE_ENVIRONMENTS
    ]


def require_safe_environment(
    env: Mapping[str, str] | None = None, *, allow_production: bool = False
) -> None:
    env = os.environ if env is None else env
    found = problems(env)
    if not found:
        return
    if allow_production and env.get(OVERRIDE_ENV, "") == OVERRIDE_VALUE:
        return
    raise SeedRefused(
        "refusing to touch data: "
        + "; ".join(found)
        + f". Seed data is for development only. To override you must pass --allow-production "
        f"AND set {OVERRIDE_ENV}={OVERRIDE_VALUE}."
    )
