"""Logging for provider calls that cannot leak (generated).

A call is logged by kind, adapter, tenant, outcome, duration and the SHAPE of the request (field names
and sizes), never a body, a header or a credential. Everything also goes through app.core.redact, and
every decrypted credential is registered there so a stray copy is hidden by value too."""

from typing import Any

import structlog
from pydantic import BaseModel

from app.core import redact

logger = structlog.get_logger("providers")


def shape(request: BaseModel) -> dict[str, str]:
    """Field name -> type and length (`str:42`), never the value."""
    out: dict[str, str] = {}
    for name, value in request.model_dump().items():
        if isinstance(value, str):
            out[name] = f"str:{len(value)}"
        elif isinstance(value, dict | list | tuple):
            out[name] = f"{type(value).__name__}:{len(value)}"
        else:
            out[name] = type(value).__name__
    return out


def log(event: str, **fields: Any) -> None:
    logger.info(event, **redact.scrub(fields))


def warn(event: str, **fields: Any) -> None:
    logger.warning(event, **redact.scrub(fields))


def register(values: dict[str, str]) -> None:
    """Hide these credential values by value from now on, wherever they turn up."""
    for value in values.values():
        redact.register_secret(value)
