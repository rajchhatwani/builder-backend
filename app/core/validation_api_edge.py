"""Validation for the `api_edge` section (idempotency keys, rate limits and quotas, dated API versions).
Issues go through `add(path, code, message)`. Nothing here runs anything: it checks shape and ranges.
Unknown keys never reach this module (the schema forbids them)."""

import re
from collections.abc import Callable
from datetime import date

from app.core.spec_models import Spec, SpecRateBucket

Add = Callable[[str, str, str], None]

API_EDGE_TABLES = ("api_idempotency", "api_quota_usage", "api_rate_buckets")
MUTATING_METHODS = ("POST", "PUT", "PATCH", "DELETE")
ALL_METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE")
PERIODS = ("day", "month")
MIN_TTL_HOURS = 1
MAX_TTL_HOURS = 168  # 7 days: a replay outlives a role revocation by at most this long (see idempotency.py)
MIN_RESPONSE_BYTES = 1024
MAX_RESPONSE_BYTES = 1_048_576
MAX_CAPACITY = 1_000_000
MIN_REFILL = 0.001
MAX_REFILL = 100_000.0
MAX_GROUPS = 50
MAX_QUOTAS = 50
MAX_QUOTA_LIMIT = 10**12
MAX_VERSIONS = 50
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PATH_RE = re.compile(r"^/[A-Za-z0-9_\-./]*$")


def api_edge_active(spec: Spec) -> bool:
    edge = spec.api_edge
    return edge is not None and edge.enabled


def idempotency_active(spec: Spec) -> bool:
    return api_edge_active(spec) and spec.api_edge is not None and spec.api_edge.idempotency is not None


def rate_limits_active(spec: Spec) -> bool:
    return api_edge_active(spec) and spec.api_edge is not None and spec.api_edge.rate_limits is not None


def quotas_active(spec: Spec) -> bool:
    return api_edge_active(spec) and spec.api_edge is not None and bool(spec.api_edge.quotas)


def api_edge_tables_active(spec: Spec) -> bool:
    """True when any part that stores rows (idempotency, rate limits, quotas) is on."""
    return idempotency_active(spec) or rate_limits_active(spec) or quotas_active(spec)


def api_edge_tables(spec: Spec) -> tuple[str, ...]:
    """The tables this spec's api_edge actually creates."""
    out = []
    if idempotency_active(spec):
        out.append("api_idempotency")
    if quotas_active(spec):
        out.append("api_quota_usage")
    if rate_limits_active(spec):
        out.append("api_rate_buckets")
    return tuple(out)


def versioning_active(spec: Spec) -> bool:
    return api_edge_active(spec) and spec.api_edge is not None and spec.api_edge.versioning is not None


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _bucket(path: str, bucket: SpecRateBucket, add: Add) -> bool:
    ok = True
    if not _is_int(bucket.capacity) or not 1 <= bucket.capacity <= MAX_CAPACITY:
        add(f"{path}.capacity", "invalid_value", f"capacity must be a whole number from 1 to {MAX_CAPACITY}")
        ok = False
    if isinstance(bucket.refill_per_second, bool) or not MIN_REFILL <= bucket.refill_per_second <= MAX_REFILL:
        add(
            f"{path}.refill_per_second",
            "invalid_value",
            f"refill_per_second must be from {MIN_REFILL:g} to {MAX_REFILL:g}",
        )
        ok = False
    return ok


def _methods(path: str, methods: list[str], allowed: tuple[str, ...], add: Add) -> None:
    for method in methods:
        if method not in allowed:
            add(path, "unknown_method", f"{method!r} is not one of: {', '.join(allowed)} (upper case)")
    if len(set(methods)) != len(methods):
        add(path, "duplicate_method", "a method is listed twice")


def _prefix(path: str, prefix: str, add: Add) -> None:
    if len(prefix) > 200 or _PATH_RE.fullmatch(prefix) is None or ".." in prefix or "//" in prefix:
        add(path, "invalid_path", "path_prefix must start with / and use only letters, digits and _-./")


def _check_idempotency(spec: Spec, add: Add) -> None:
    cfg = spec.api_edge.idempotency if spec.api_edge is not None else None
    if cfg is None:
        return
    if not cfg.methods:
        add("api_edge.idempotency.methods", "required", "list at least one method")
    _methods("api_edge.idempotency.methods", cfg.methods, MUTATING_METHODS, add)
    if not _is_int(cfg.ttl_hours) or not MIN_TTL_HOURS <= cfg.ttl_hours <= MAX_TTL_HOURS:
        add("api_edge.idempotency.ttl_hours", "invalid_value", f"ttl_hours must be {MIN_TTL_HOURS} to {MAX_TTL_HOURS} (7 days at most: a stored response is replayed until it expires)")
    if not _is_int(cfg.max_response_bytes) or not MIN_RESPONSE_BYTES <= cfg.max_response_bytes <= MAX_RESPONSE_BYTES:
        add(
            "api_edge.idempotency.max_response_bytes",
            "invalid_value",
            f"max_response_bytes must be {MIN_RESPONSE_BYTES} to {MAX_RESPONSE_BYTES}",
        )


def _check_rate_limits(spec: Spec, add: Add) -> None:
    cfg = spec.api_edge.rate_limits if spec.api_edge is not None else None
    if cfg is None:
        return
    base = "api_edge.rate_limits"
    ok_user = _bucket(f"{base}.user", cfg.user, add)
    _bucket(f"{base}.anonymous", cfg.anonymous, add)
    ok_tenant = cfg.tenant is None or _bucket(f"{base}.tenant", cfg.tenant, add)
    if len(cfg.groups) > MAX_GROUPS:
        add(f"{base}.groups", "too_many", f"at most {MAX_GROUPS} groups")
    seen: set[str] = set()
    for i, group in enumerate(cfg.groups):
        path = f"{base}.groups[{i}]"
        if _NAME_RE.fullmatch(group.name) is None or group.name == "default":
            add(f"{path}.name", "invalid_name", "use a lower-case identifier (not 'default'), up to 40 characters")
        elif group.name in seen:
            add(f"{path}.name", "duplicate", f"group {group.name!r} is declared twice")
        seen.add(group.name)
        _prefix(f"{path}.path_prefix", group.path_prefix, add)
        _methods(f"{path}.methods", group.methods, ALL_METHODS, add)
        capacities = []
        for label, override, default, default_ok in (
            ("user", group.user, cfg.user, ok_user),
            ("tenant", group.tenant, cfg.tenant, ok_tenant),
        ):
            if override is not None:
                if _bucket(f"{path}.{label}", override, add):
                    capacities.append(override.capacity)
            elif default is not None and default_ok:
                capacities.append(default.capacity)
        if not _is_int(group.cost) or group.cost < 1:
            add(f"{path}.cost", "invalid_value", "cost must be a whole number of at least 1")
        elif capacities and group.cost > min(capacities):
            add(f"{path}.cost", "invalid_value", "cost is larger than a bucket's capacity: the route could never be called")


def _check_quotas(spec: Spec, add: Add) -> None:
    edge = spec.api_edge
    if edge is None:
        return
    if len(edge.quotas) > MAX_QUOTAS:
        add("api_edge.quotas", "too_many", f"at most {MAX_QUOTAS} quotas")
    seen: set[str] = set()
    for i, quota in enumerate(edge.quotas):
        path = f"api_edge.quotas[{i}]"
        if _NAME_RE.fullmatch(quota.meter) is None:
            add(f"{path}.meter", "invalid_name", "use a lower-case identifier, up to 40 characters")
        elif quota.meter in seen:
            add(f"{path}.meter", "duplicate", f"meter {quota.meter!r} is declared twice")
        seen.add(quota.meter)
        if quota.period not in PERIODS:
            add(f"{path}.period", "unknown_period", f"period must be one of: {', '.join(PERIODS)}")
        if not _is_int(quota.limit) or not 1 <= quota.limit <= MAX_QUOTA_LIMIT:
            add(f"{path}.limit", "invalid_value", f"limit must be a whole number from 1 to {MAX_QUOTA_LIMIT}")
        elif not _is_int(quota.cost) or not 1 <= quota.cost <= quota.limit:
            add(f"{path}.cost", "invalid_value", "cost must be a whole number from 1 to the limit")
        _prefix(f"{path}.path_prefix", quota.path_prefix, add)
        _methods(f"{path}.methods", quota.methods, ALL_METHODS, add)


def _check_versioning(spec: Spec, add: Add) -> None:
    cfg = spec.api_edge.versioning if spec.api_edge is not None else None
    if cfg is None:
        return
    dates: list[str] = []
    if not cfg.versions:
        add("api_edge.versioning.versions", "required", "declare at least one version")
    if len(cfg.versions) > MAX_VERSIONS:
        add("api_edge.versioning.versions", "too_many", f"at most {MAX_VERSIONS} versions")
    for i, version in enumerate(cfg.versions):
        path = f"api_edge.versioning.versions[{i}]"
        if not _valid_date(version.date):
            add(f"{path}.date", "invalid_date", "a version is a real calendar date written YYYY-MM-DD")
        elif version.date in dates:
            add(f"{path}.date", "duplicate", f"version {version.date} is declared twice")
        else:
            dates.append(version.date)
        if len(version.note) > 300:
            add(f"{path}.note", "too_long", "note must be at most 300 characters")
    if not _valid_date(cfg.default):
        add("api_edge.versioning.default", "invalid_date", "default must be a date written YYYY-MM-DD")
    elif cfg.default not in dates:
        add("api_edge.versioning.default", "unknown_version", "default must be one of the declared versions")


def _valid_date(value: str) -> bool:
    if _DATE_RE.fullmatch(value) is None:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def check_api_edge(spec: Spec, add: Add) -> None:
    edge = spec.api_edge
    if edge is None or not edge.enabled:
        return
    if edge.idempotency is None and edge.rate_limits is None and not edge.quotas and edge.versioning is None:
        add("api_edge", "empty", "enable at least one of: idempotency, rate_limits, quotas, versioning")
    _check_idempotency(spec, add)
    _check_rate_limits(spec, add)
    _check_quotas(spec, add)
    _check_versioning(spec, add)
