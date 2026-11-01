"""Provider settings read from the environment (generated). A bad value stops the process.

PROVIDER_VAULT_KEY          master key of the credential vault (at least 32 characters). Never in the
                            spec, the database or the generated files.
PROVIDER_VAULT_KEY_VERSION  the version number of that key (default 1). Raise it when you rotate.
PROVIDER_VAULT_KEY_PREVIOUS older keys that can still decrypt, as `version=key` pairs separated by
                            commas, e.g. `1=old-key-of-at-least-32-characters`. Run
                            `python -m app.providers.reencrypt` and then drop them.
"""

import os
import re

from app.providers.errors import VaultError

MIN_KEY_LENGTH = 32
_WEAK_WORDS = ("changeme", "change-me", "change_me", "default", "placeholder", "replace-me", "your-key", "example", "unused")
_PAIR_RE = re.compile(r"\s*([1-9][0-9]{0,5})\s*=\s*(\S+)\s*")


# Default deny: only these names are development-like. Anything else (production, prod, staging, a
# typo, or APP_ENV unset) is treated as production: the key check is enforced and the emulator is
# refused when a tenant has no credentials.
DEVELOPMENT_ENVS = frozenset({"local", "dev", "development", "test", "testing", "demo", "preview"})


def app_env() -> str:
    """APP_ENV, trimmed and lower-cased; empty when unset."""
    return os.environ.get("APP_ENV", "").strip().lower()


def is_production() -> bool:
    """True unless APP_ENV is an explicit development-like name (unset counts as production)."""
    return app_env() not in DEVELOPMENT_ENVS


def is_test() -> bool:
    return app_env() == "test"


def key_problem(key: str) -> str | None:
    """Why `key` cannot be a master key (the key itself is never in the text)."""
    if len(key) < MIN_KEY_LENGTH:
        return f"must be at least {MIN_KEY_LENGTH} characters"
    if len(set(key)) < 8:
        return "is too repetitive"
    lowered = key.lower()
    if any(word in lowered for word in _WEAK_WORDS):
        return "looks like a placeholder"
    return None


def _version() -> int:
    raw = os.environ.get("PROVIDER_VAULT_KEY_VERSION", "1").strip() or "1"
    if not raw.isdigit() or not 1 <= int(raw) <= 999_999:
        raise VaultError("PROVIDER_VAULT_KEY_VERSION must be a whole number from 1")
    return int(raw)


def vault_keys() -> tuple[int, dict[int, str]]:
    """The current key version and every key by version (current included). Raises VaultError."""
    key = os.environ.get("PROVIDER_VAULT_KEY", "").strip()
    if not key:
        raise VaultError("PROVIDER_VAULT_KEY is not set")
    problem = key_problem(key)
    if problem is not None:
        raise VaultError(f"PROVIDER_VAULT_KEY {problem}")
    current = _version()
    keys = {current: key}
    previous = os.environ.get("PROVIDER_VAULT_KEY_PREVIOUS", "").strip()
    for part in [p for p in previous.split(",") if p.strip()]:
        match = _PAIR_RE.fullmatch(part)
        if match is None:
            raise VaultError("PROVIDER_VAULT_KEY_PREVIOUS must be `version=key` pairs separated by commas")
        version, old = int(match.group(1)), match.group(2)
        if version == current or version in keys:
            raise VaultError("PROVIDER_VAULT_KEY_PREVIOUS repeats a key version")
        if key_problem(old) is not None:
            raise VaultError(f"a key in PROVIDER_VAULT_KEY_PREVIOUS {key_problem(old)}")
        keys[version] = old
    return current, keys


def check_boot() -> None:
    """Called at start-up: in production a missing, short or placeholder key stops the app."""
    if is_production():
        vault_keys()
