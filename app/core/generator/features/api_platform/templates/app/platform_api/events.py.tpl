"""Signed app events (generated).

This module only signs and verifies: no outbound HTTP request is made here. Delivery rides the project's webhooks
block, which posts the headers and body `signed_event` returns. Nothing is signed for an installation that is
uninstalled, revoked or expired (`deliverable`), nor for an event type the app did not declare.

The signing secret is never stored: it is HMAC-SHA256 under the server's PLATFORM_SIGNING_KEY (environment, at least
32 characters) over the installation id (`signing_secret_for`) and shown once, at install. A database leak alone
cannot forge an event. Without the key nothing is signed and installing an app is refused (fail closed)."""

import datetime as _dt
import hashlib
import hmac
import json
import os
import time
from typing import Any

from app.core.errors import AppError
from app.platform_api import settings

_DOMAIN = b"event-signing-v1"
HEADER_TYPE = "X-Event-Type"
HEADER_TIMESTAMP = "X-Event-Timestamp"
HEADER_SIGNATURE = "X-Event-Signature"


SIGNING_KEY_ENV = "PLATFORM_SIGNING_KEY"
MIN_SIGNING_KEY = 32


def require_signing_key() -> str:
    key = os.environ.get(SIGNING_KEY_ENV, "")
    if len(key) < MIN_SIGNING_KEY:
        raise AppError("signing_key_missing", f"set {SIGNING_KEY_ENV} (at least {MIN_SIGNING_KEY} characters)", 503)
    return key


def signing_secret_for(installation_id: Any) -> str:
    key = require_signing_key()
    return hmac.new(key.encode(), _DOMAIN + b":" + str(installation_id).encode(), hashlib.sha256).hexdigest()


def sign(secret: str, timestamp: int | str, body: str) -> str:
    digest = hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify(secret: str, timestamp: int | str, body: str, signature: str, tolerance: int = 300) -> bool:
    """Constant time; a timestamp more than `tolerance` seconds from now is refused (replay)."""
    try:
        age = abs(time.time() - int(timestamp))
    except (TypeError, ValueError):
        return False
    if age > tolerance:
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), signature)


def deliverable(installation: Any) -> bool:
    """True only for an active app installation (an `api_keys` row of kind 'app')."""
    if getattr(installation, "kind", None) != "app" or installation.revoked_at is not None:
        return False
    return bool(installation.expires_at > _dt.datetime.now(_dt.UTC))


def signed_event(installation: Any, event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Headers + body to post, or None when the installation is not active or the app did not declare the type."""
    app = settings.APPS.get(installation.app or "")
    if app is None or not deliverable(installation) or event_type not in app["events"]:
        return None
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    timestamp = int(time.time())
    secret = signing_secret_for(installation.id)
    headers = {
        HEADER_TYPE: event_type,
        HEADER_TIMESTAMP: str(timestamp),
        HEADER_SIGNATURE: sign(secret, timestamp, body),
    }
    return {"headers": headers, "body": body}
