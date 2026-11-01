"""Dated API versions (generated).

A version is a date. The newest declared version is the shape the code produces; for an older client
each newer version's transformer (app/hooks/api_versions.py, yours) undoes that version's change, newest
first. Transformers are pure functions of (method, path, body) and apply to successful JSON responses."""

import copy
import re
from collections.abc import Callable
from typing import Any

from app.api_edge import definitions
from app.core.errors import AppError

Transformer = Callable[[str, str, Any], Any]

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
if definitions.VERSIONING is None:
    raise RuntimeError("app/api_edge/versioning.py is generated only for projects with api_edge.versioning")
_CFG: dict[str, Any] = definitions.VERSIONING
DEFAULT: str = _CFG["default"]
VERSIONS: tuple[str, ...] = tuple(sorted(v["date"] for v in _CFG["versions"]))
LATEST: str = VERSIONS[-1]
_EXEMPT = ("/docs", "/redoc", "/openapi.json", "/health")


def exempt(path: str) -> bool:
    """Documentation, health and the changelog have no versioned shape."""
    return path == "/api-versions" or any(path == p or path.startswith(p + "/") for p in _EXEMPT)


def resolve(raw: str | None) -> str:
    """The version a request is served in: the header, else the project's pinned default."""
    if raw is None:
        return DEFAULT
    if DATE_RE.fullmatch(raw) is None or raw not in VERSIONS:
        raise AppError(
            "unsupported_api_version",
            f"API-Version must be one of: {', '.join(VERSIONS)}",
            400,
            [{"supported": list(VERSIONS), "default": DEFAULT}],
        )
    return raw


def registry() -> dict[str, Transformer]:
    from app.hooks import api_versions

    return dict(api_versions.TRANSFORMERS)


def check_registry() -> None:
    """Start-up check: a transformer for a version nobody declared is a mistake."""
    for date, fn in registry().items():
        if date not in VERSIONS or not callable(fn):
            raise ValueError(
                f"app/hooks/api_versions.py: {date!r} is not a declared API version, or not callable"
            )


def pending(version: str) -> list[tuple[str, Transformer]]:
    """The transformers that bring a response from the newest shape down to `version`, newest first."""
    table = registry()
    return [(d, table[d]) for d in sorted(table, reverse=True) if d > version and d in VERSIONS]


def downgrade(version: str, method: str, path: str, body: Any) -> Any:
    for _date, fn in pending(version):
        body = fn(method, path, copy.deepcopy(body))
    return body


def changelog() -> dict[str, Any]:
    table = registry()
    return {
        "default": DEFAULT,
        "latest": LATEST,
        "versions": [
            {"date": v["date"], "note": v["note"], "transformer": v["date"] in table}
            for v in sorted(_CFG["versions"], key=lambda x: x["date"], reverse=True)
        ],
    }
