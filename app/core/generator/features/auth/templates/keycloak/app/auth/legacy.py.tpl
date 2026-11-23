"""Legacy sign-in while this app moves to the suite hub (generated, identity path b).

Before the move this app signed its own tokens (HS256, issuer `LEGACY_ISSUER`). While the
migration is open those tokens keep working, resolved through `auth_identities` to the SAME local
user, and only inside the window the spec gave:

    legacy_read_only   legacy ACCESS tokens work for GET / HEAD / OPTIONS only
    dual               legacy access tokens work for everything until LEGACY_DUAL_UNTIL
    hub_only           legacy access AND refresh tokens are refused; nothing here accepts them

The window comes from the generated config, never from the request, and every doubt (unparsable
date, missing or short secret, wrong header, wrong issuer or type, expiry) refuses. Legacy refresh
tokens are opaque database rows of the old app and are never accepted here: a client signs in at
the hub to get a new token. Nothing here creates a user: an unknown legacy subject is refused.
"""

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import time
from typing import Any

from app.auth import config

_HEADER = {"alg": "HS256", "typ": "JWT"}
_SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
_MIN_SECRET_BYTES = 32
_MAX_TOKEN_BYTES = 8192
_LEEWAY_SECONDS = 30


class LegacyRefused(Exception):
    """A legacy credential must not be trusted. The message is for logs, never for the caller."""


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _b64d(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def window_end() -> dt.datetime | None:
    """The end of the dual window, or None when there is no usable one (fails closed)."""
    raw = config.LEGACY_DUAL_UNTIL
    if raw is None:
        return None
    try:
        end = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    return end if end.tzinfo is not None else None


def peek_issuer(raw_token: str) -> str | None:
    """The unverified `iss` of a token. Only used to choose WHICH check runs; it grants nothing."""
    try:
        if len(raw_token.encode("utf-8", errors="replace")) > _MAX_TOKEN_BYTES:
            return None
        parts = raw_token.split(".")
        if len(parts) != 3:
            return None
        payload = json.loads(_b64d(parts[1]))
        issuer = payload.get("iss") if isinstance(payload, dict) else None
        return issuer if isinstance(issuer, str) else None
    except (ValueError, TypeError, UnicodeError):
        return None


def is_legacy_issuer(issuer: str | None) -> bool:
    return issuer is not None and issuer == config.LEGACY_ISSUER


def refusal(method: str, kind: str = "access") -> str | None:
    """Why a legacy credential of `kind` ('access' or 'refresh') is refused for `method`, or None."""
    if kind != "access":
        return "legacy refresh tokens are not accepted: sign in at the hub"
    state = config.LEGACY_STATE
    if state == "hub_only":
        return "legacy sign-in is closed (hub_only)"
    if state == "legacy_read_only":
        if method.upper() not in _SAFE_METHODS:
            return "legacy tokens are read-only during legacy_read_only"
        return None
    if state == "dual":
        end = window_end()
        if end is None:
            return "the dual window is not usable"
        if _now() >= end:
            return "the dual window has ended"
        return None
    return "unknown migration state"


def verify_access(raw_token: str, method: str, *, kind: str = "access") -> dict[str, Any]:
    """The claims of a valid legacy access token. Raises LegacyRefused otherwise."""
    reason = refusal(method, kind)
    if reason is not None:
        raise LegacyRefused(reason)
    secret = os.environ.get("LEGACY_JWT_SECRET", "")
    if len(secret.encode("utf-8")) < _MIN_SECRET_BYTES:
        raise LegacyRefused("LEGACY_JWT_SECRET is missing or too short")
    if len(raw_token.encode("utf-8", errors="replace")) > _MAX_TOKEN_BYTES:
        raise LegacyRefused("token too large")
    try:
        head_part, payload_part, signature = raw_token.split(".")
        if json.loads(_b64d(head_part)) != _HEADER:
            raise LegacyRefused("unsupported token header")
        expected = base64.urlsafe_b64encode(
            hmac.new(
                secret.encode("utf-8"),
                f"{head_part}.{payload_part}".encode("ascii"),
                hashlib.sha256,
            ).digest()
        ).rstrip(b"=").decode("ascii")
        if not hmac.compare_digest(signature, expected):
            raise LegacyRefused("bad signature")
        claims = json.loads(_b64d(payload_part))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise LegacyRefused("malformed token") from exc
    if not isinstance(claims, dict):
        raise LegacyRefused("malformed token")
    now = time.time()
    exp, iat = claims.get("exp"), claims.get("iat")
    if not isinstance(exp, int | float) or exp <= now:
        raise LegacyRefused("token expired")
    if isinstance(iat, int | float) and iat > now + _LEEWAY_SECONDS:
        raise LegacyRefused("issued in the future")
    if claims.get("type") != "access":
        raise LegacyRefused("not an access token")
    if claims.get("iss") != config.LEGACY_ISSUER:
        raise LegacyRefused("wrong issuer")
    subject = claims.get("sub")
    if not isinstance(subject, str) or not 0 < len(subject) <= 255 or not subject.isprintable():
        raise LegacyRefused("bad subject")
    return claims
