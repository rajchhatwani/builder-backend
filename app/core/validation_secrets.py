"""Secrets never live in the spec: scan every string of the single-object blocks (events, providers,
notifications, jobs, workflows, api_edge, webhooks, hook_effects), whether or not the block is
enabled (a disabled block is still stored and returned by GET /spec). Issues are `secret_in_spec`."""

import re
from collections.abc import Callable
from typing import Any

from app.core.spec_models import Spec
from app.core.validation_providers import secret_key_name, secret_value

Add = Callable[[str, str, str], None]

BLOCKS = (
    "events",
    "providers",
    "notifications",
    "jobs",
    "workflows",
    "api_edge",
    "webhooks",
    "hook_effects",
)
# A long, space-free, token-looking string (hex, base64, base64url).
_TOKENISH = re.compile(r"[A-Za-z0-9+/=_.-]{20,}")


def _walk(value: Any, path: str, key: str, add: Add) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _walk(v, f"{path}.{k}", str(k), add)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _walk(v, f"{path}[{i}]", key, add)
    elif isinstance(value, str):
        if secret_value(value):
            add(path, "secret_in_spec", "this value looks like a credential: credentials go in the vault API")
        elif secret_key_name(key) and _TOKENISH.fullmatch(value) and not value.isalpha():
            add(path, "secret_in_spec", f"{key!r} holds a long token-like value: credentials go in the vault API")


def check_block_secrets(spec: Spec, add: Add) -> None:
    for block in BLOCKS:
        model = getattr(spec, block)
        if model is not None:
            _walk(model.model_dump(mode="json"), block, block, add)
