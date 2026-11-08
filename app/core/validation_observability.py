"""Validation for the `observability` block. Issues go through the `add(path, code, message)`
callable that validation.validate passes in."""

import math
from collections.abc import Callable

from app.core import observability as obs
from app.core.spec_models import Spec, SpecObservability

Add = Callable[[str, str, str], None]


def check_observability(spec: Spec, add: Add) -> None:
    block = spec.observability
    if block is None:
        return
    if block.service_name is not None and not obs.SERVICE_NAME_RE.fullmatch(block.service_name):
        add(
            "observability.service_name",
            "invalid_value",
            "use lowercase letters, digits, '-' and '_', starting with a letter (max 63)",
        )
    ratio = block.sample_ratio
    if isinstance(ratio, bool) or not math.isfinite(ratio) or not 0 <= ratio <= 1:
        add("observability.sample_ratio", "invalid_value", "must be a number from 0 to 1")
    if len(block.exclude_paths) > obs.MAX_EXCLUDE_PATHS:
        add(
            "observability.exclude_paths",
            "too_many",
            f"at most {obs.MAX_EXCLUDE_PATHS} paths",
        )
    seen: set[str] = set()
    for i, path in enumerate(block.exclude_paths):
        where = f"observability.exclude_paths[{i}]"
        if not obs.PATH_RE.fullmatch(path):
            add(where, "invalid_value", "a path starts with '/' and uses letters, digits and /_.-")
        elif path in seen:
            add(where, "duplicate", f"{path} is listed twice")
        seen.add(path)
    if len(block.extra_redact_keys) > obs.MAX_REDACT_KEYS:
        add("observability.extra_redact_keys", "too_many", f"at most {obs.MAX_REDACT_KEYS} keys")
    for i, key in enumerate(block.extra_redact_keys):
        if not obs.REDACT_KEY_RE.fullmatch(key):
            add(
                f"observability.extra_redact_keys[{i}]",
                "invalid_value",
                "use lowercase letters, digits, '_', '-' and '.' (2 to 40 characters)",
            )
    if block.expected_rps is not None and not 1 <= block.expected_rps <= 1_000_000:
        add("observability.expected_rps", "invalid_value", "must be between 1 and 1,000,000")


def observability_active(spec: Spec) -> SpecObservability | None:
    """The observability block when it is switched on, else None."""
    block = spec.observability
    return block if block is not None and block.enabled else None
