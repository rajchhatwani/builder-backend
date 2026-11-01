"""Production guard (generated). Seed data is for development and demos only.

Seeding and resetting refuse to run unless APP_ENV (and ENVIRONMENT, when set) names a development-like
environment. A missing value, `production`, `staging` or any name not on the list is refused. Overriding
needs BOTH the `--allow-production` flag AND the environment variable SEED_ALLOW_PRODUCTION=yes.

The database host in DATABASE_URL must also be local or compose-internal (SAFE_DB_HOSTS). A remote, missing
or unparsable host is refused, with the same double override. The check fails closed: a URL with a fragment,
a host/hostaddr/port/service query parameter, several hosts, a unix socket or an odd host is refused too.
"""

import os
import re
from collections.abc import Mapping
from urllib.parse import unquote, urlsplit

SAFE_ENVIRONMENTS = frozenset({"local", "dev", "development", "test", "testing", "demo", "preview"})
ENV_NAMES = ("APP_ENV", "ENVIRONMENT")
DB_URL_ENV = "DATABASE_URL"
# Local and compose-internal hosts only (`db` and `pgbouncer` are the compose service names).
SAFE_DB_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "db", "pgbouncer"})
OVERRIDE_ENV = "SEED_ALLOW_PRODUCTION"
OVERRIDE_VALUE = "yes"


class SeedRefused(Exception):
    """The environment is not a development one (or the override is incomplete)."""


# libpq/asyncpg let these query parameters replace or add to the host in the URL, so a URL that sets any of them
# cannot be judged by its netloc alone and is refused.
FORBIDDEN_QUERY_KEYS = frozenset({"host", "hostaddr", "port", "service"})
# dbname may itself hold a whole connection string (libpq expands `postgresql://...` and `k=v` forms).
CONNINFO_KEYS = frozenset({"dbname", "database"})


def _has_odd_chars(text: str) -> bool:
    return any(ch.isspace() or not ch.isprintable() or not ch.isascii() for ch in text)


def url_problems(url: str) -> list[str]:
    """Why DATABASE_URL cannot be trusted to point at a local database (empty list when it can). Fails closed:
    anything unusual, ambiguous or unparsable is a problem."""
    if not url.strip():
        return [f"{DB_URL_ENV} is missing or has no readable host, so the database is unknown"]
    if _has_odd_chars(url.strip()) and not url.strip().isascii():
        return [f"{DB_URL_ENV} contains non-ASCII characters, so its host is ambiguous"]
    try:
        parts = urlsplit(url.strip())
        raw_host = parts.hostname
    except ValueError:
        return [f"{DB_URL_ENV} cannot be parsed, so the database is unknown"]
    found: list[str] = []
    if parts.fragment or "#" in url:
        found.append(f"{DB_URL_ENV} has a fragment (#...), which can hide a different host")
    if "," in unquote(parts.netloc):
        found.append(f"{DB_URL_ENV} lists more than one host (multi-host form)")
    for pair in re.split(r"[&;]", parts.query):
        if not pair:
            continue
        key, _, value = pair.partition("=")
        key = unquote(key).strip().lower()
        if key in FORBIDDEN_QUERY_KEYS:
            found.append(f"{DB_URL_ENV} sets {key!r} in its query, which overrides the host in the URL")
        elif key in CONNINFO_KEYS and ("=" in unquote(value) or "://" in unquote(value)):
            found.append(f"{DB_URL_ENV} sets {key!r} to a connection string, which can name another host")
    path = unquote(parts.path)
    if "=" in path or "://" in path:
        found.append(f"{DB_URL_ENV} has a connection string in its database name, which can name another host")
    if raw_host is None or not raw_host:
        found.append(f"{DB_URL_ENV} is missing or has no readable host (a unix socket is not a safe host)")
        return found
    host = unquote(raw_host)
    if _has_odd_chars(host) or host.endswith(".") or "," in host:
        found.append(f"database host {host!r} has whitespace, control, non-ASCII characters or a trailing dot")
    elif host.lower() not in SAFE_DB_HOSTS:
        found.append(f"database host {host.lower()!r} is not local (allowed: {', '.join(sorted(SAFE_DB_HOSTS))})")
    return found


def database_host(env: Mapping[str, str]) -> str | None:
    """The lower-cased, percent-decoded host of DATABASE_URL, or None when it is missing or cannot be parsed."""
    url = env.get(DB_URL_ENV, "").strip()
    if not url:
        return None
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    return unquote(host).lower() if host else None


def problems(env: Mapping[str, str]) -> list[str]:
    return environment_problems(env) + database_problems(env)


def database_problems(env: Mapping[str, str]) -> list[str]:
    return url_problems(env.get(DB_URL_ENV, ""))


def environment_problems(env: Mapping[str, str]) -> list[str]:
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
        + f". Seed data is for development only, on a local database. To override you must pass --allow-production "
        f"AND set {OVERRIDE_ENV}={OVERRIDE_VALUE}."
    )
