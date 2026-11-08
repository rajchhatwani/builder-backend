"""Validation for the `providers` section (adapter framework + per-tenant credential vault). Issues go
through `add(path, code, message)`. The spec holds provider NAMES and non-secret settings only: any
key or value that looks like a secret is refused with `secret_in_spec`."""

import re
from collections.abc import Callable

from app.core.spec_models import Spec
from app.core.validation_runtime import looks_secret

Add = Callable[[str, str, str], None]

PROVIDER_TABLES = ("provider_credentials",)
KINDS = ("email", "sms", "push", "payments", "storage", "llm", "generic")
RESERVED_NAMES = ("emulator",)
NAME_RE = re.compile(r"[a-z][a-z0-9_]{1,39}")
SETTING_KEY_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")
MAX_ADAPTERS = 50
MAX_SETTINGS = 20
MAX_SETTING_VALUE = 500

# Same shape as the generated app/core/redact.py key pattern, plus credential-ish words.
_SECRET_KEY_RE = re.compile(
    r"(pass(word|wd)?|secret|token|authorization|signature|api[-_]?key|key|cookie|credential|"
    r"private[-_]?key|client[-_]?secret|bearer)",
    re.IGNORECASE,
)
# Values that look like credentials whatever the key is called.
_SECRET_VALUE_RES = (
    re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{8,}"),
    re.compile(r"\bwhsec_[A-Za-z0-9+/=_-]{8,}"),
    re.compile(r"\brzp_(?:live|test)_[A-Za-z0-9]{6,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{30,}"),
    re.compile(r"\bnpm_[A-Za-z0-9]{30,}"),
    re.compile(r"\b[0-9a-fA-F]{40,}\b"),  # a bare 160-bit+ hex string
)


def providers_active(spec: Spec) -> bool:
    return spec.providers is not None and spec.providers.enabled


def secret_key_name(name: str) -> bool:
    return looks_secret(name) or bool(_SECRET_KEY_RE.search(name))


def secret_value(value: object) -> bool:
    return isinstance(value, str) and any(r.search(value) for r in _SECRET_VALUE_RES)


def check_providers(spec: Spec, add: Add) -> None:
    pv = spec.providers
    if pv is None or not pv.enabled:
        return
    if spec.auth is None or not spec.auth.enabled:
        add("providers", "needs_auth", "the credential vault is an admin API: enable auth first")
    else:
        roles = {r.name for r in spec.auth.roles}
        if pv.admin_role not in roles:
            add("providers.admin_role", "unknown_role", f"admin_role {pv.admin_role!r} is not a role of the project")
    if not spec.entities:
        add("providers", "no_entities", "providers need at least one entity")
    if isinstance(pv.timeout_seconds, bool) or not 0.1 <= pv.timeout_seconds <= 120:
        add("providers.timeout_seconds", "invalid_value", "timeout_seconds must be 0.1 to 120")
    if isinstance(pv.max_attempts, bool) or not 1 <= pv.max_attempts <= 10:
        add("providers.max_attempts", "invalid_value", "max_attempts must be 1 to 10")
    if isinstance(pv.breaker_failures, bool) or not 1 <= pv.breaker_failures <= 100:
        add("providers.breaker_failures", "invalid_value", "breaker_failures must be 1 to 100")
    if isinstance(pv.breaker_reset_seconds, bool) or not 0.1 <= pv.breaker_reset_seconds <= 3600:
        add("providers.breaker_reset_seconds", "invalid_value", "breaker_reset_seconds must be 0.1 to 3600")
    if len(pv.adapters) > MAX_ADAPTERS:
        add("providers.adapters", "too_many", f"at most {MAX_ADAPTERS} adapters")
    seen: set[tuple[str, str]] = set()
    for i, adapter in enumerate(pv.adapters):
        path = f"providers.adapters[{i}]"
        if adapter.kind not in KINDS:
            add(f"{path}.kind", "unknown_kind", f"kind must be one of: {', '.join(KINDS)}")
        if adapter.name in RESERVED_NAMES:
            add(f"{path}.name", "reserved_name", f"{adapter.name!r} is built in for every kind: do not list it")
        elif not NAME_RE.fullmatch(adapter.name):
            add(f"{path}.name", "invalid_name", "name must be lowercase letters, digits and underscores (2-40)")
        elif secret_key_name(adapter.name) or secret_value(adapter.name):
            add(f"{path}.name", "secret_in_spec", "a provider name must not look like a credential")
        if (adapter.kind, adapter.name) in seen:
            add(path, "duplicate_adapter", f"{adapter.kind}/{adapter.name} is listed twice")
        seen.add((adapter.kind, adapter.name))
        if len(adapter.settings) > MAX_SETTINGS:
            add(f"{path}.settings", "too_many", f"at most {MAX_SETTINGS} settings")
        for key, value in adapter.settings.items():
            kpath = f"{path}.settings.{key}"
            if secret_key_name(key):
                add(kpath, "secret_in_spec", "the spec holds non-secret settings only: credentials go in the vault API")
            elif not SETTING_KEY_RE.fullmatch(key):
                add(kpath, "invalid_name", "setting names are lowercase letters, digits and underscores")
            if secret_value(value):
                add(kpath, "secret_in_spec", "this value looks like a credential: credentials go in the vault API")
            elif isinstance(value, str) and len(value) > MAX_SETTING_VALUE:
                add(kpath, "invalid_value", f"at most {MAX_SETTING_VALUE} characters")
