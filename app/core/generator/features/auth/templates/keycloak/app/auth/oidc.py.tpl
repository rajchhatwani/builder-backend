"""Verifies Keycloak access tokens (generated).

Every check fails closed: a token is accepted only if its signature verifies against a key
Keycloak published, and its issuer, audience, type and times are exactly right. Keys come
only from Keycloak's JWKS endpoint (never from the token), the algorithm is pinned to RS256
(so `none` and HMAC-with-the-public-key tricks do not work), and the key set is cached with
a bounded refetch rate so a stream of forged key ids cannot hammer Keycloak.
"""

import asyncio
import base64
import binascii
import datetime as dt
import json
import math
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

import structlog
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.auth import config

logger = structlog.get_logger()

_ALLOWED_ALG = "RS256"
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_MIN_KEY_BITS = 2048
_MAX_SUBJECT = 255


class InvalidTokenError(Exception):
    """The token must not be trusted. The message is for logs, never for the caller."""


class KeysUnavailableError(Exception):
    """Keycloak's signing keys could not be loaded, so no token can be checked right now."""


@dataclass(frozen=True)
class VerifiedToken:
    # The identity provider's id for the person: any text up to 255 characters, NOT a user id.
    sub: str
    issuer: str
    email: str | None
    email_verified: bool
    name: str | None
    # Keycloak's session id for this sign-in, when the token carries one.
    sid: str | None = None
    auth_time: int | None = None
    # Roles granted on this project's client, exactly as Keycloak lists them.
    roles: tuple[str, ...] = field(default_factory=tuple)
    # Aliases of the organizations (tenants) the token was issued for.
    organizations: tuple[str, ...] = field(default_factory=tuple)
    # Custom registration fields present in the token, already converted to their types (None
    # when the value was not valid for the field).
    attributes: dict[str, Any] = field(default_factory=dict)


# --- parsing ----------------------------------------------------------------------------


def _b64decode(segment: str) -> bytes:
    if not segment or not _SEGMENT_RE.fullmatch(segment):
        raise InvalidTokenError("malformed segment")
    try:
        return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    except (binascii.Error, ValueError) as exc:
        raise InvalidTokenError("malformed segment") from exc


def _json_object(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidTokenError("malformed json") from exc
    if not isinstance(value, dict):
        raise InvalidTokenError("not a json object")
    return value


def parse(token: str) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes]:
    """Split a compact JWS into (header, payload, signing input, signature) without trusting it."""
    if len(token.encode("utf-8", errors="replace")) > config.MAX_TOKEN_BYTES:
        raise InvalidTokenError("token too large")
    parts = token.split(".")
    if len(parts) != 3:
        raise InvalidTokenError("not a three part token")
    header = _json_object(_b64decode(parts[0]))
    payload = _json_object(_b64decode(parts[1]))
    signature = _b64decode(parts[2])
    return header, payload, f"{parts[0]}.{parts[1]}".encode("ascii"), signature


# --- keys -------------------------------------------------------------------------------


def _b64_int(value: Any) -> int:
    if not isinstance(value, str):
        raise ValueError("not a string")
    return int.from_bytes(_b64decode(value), "big")


def parse_jwks(document: Any) -> dict[str, rsa.RSAPublicKey]:
    """Usable RSA signing keys of a JWKS document, by key id. Anything else is ignored."""
    keys: dict[str, rsa.RSAPublicKey] = {}
    entries = document.get("keys") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        raise ValueError("no keys")
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("kty") != "RSA":
            continue
        if entry.get("use") not in (None, "sig") or entry.get("alg") not in (None, _ALLOWED_ALG):
            continue
        kid = entry.get("kid")
        if not isinstance(kid, str) or not kid:
            continue
        try:
            key = rsa.RSAPublicNumbers(_b64_int(entry.get("e")), _b64_int(entry.get("n"))).public_key()
        except (ValueError, InvalidTokenError):
            continue
        if key.key_size >= _MIN_KEY_BITS:
            keys[kid] = key
    return keys


def _fetch_jwks(url: str) -> dict[str, rsa.RSAPublicKey]:
    """Blocking download of the key set. Tests replace this."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=config.JWKS_TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise ValueError(f"unexpected status {response.status}")
        body = response.read(config.JWKS_MAX_BYTES + 1)
    if len(body) > config.JWKS_MAX_BYTES:
        raise ValueError("key set too large")
    return parse_jwks(json.loads(body))


class KeyCache:
    def __init__(self) -> None:
        self._keys: dict[str, rsa.RSAPublicKey] = {}
        self._fetched_at = float("-inf")
        self._attempted_at = float("-inf")
        self._lock = asyncio.Lock()

    def clear(self) -> None:
        self._keys = {}
        self._fetched_at = float("-inf")
        self._attempted_at = float("-inf")

    async def key_for(self, kid: str) -> rsa.RSAPublicKey:
        now = time.monotonic()
        fresh = now - self._fetched_at < config.JWKS_TTL_SECONDS
        if fresh and kid in self._keys:
            return self._keys[kid]
        async with self._lock:
            now = time.monotonic()
            fresh = now - self._fetched_at < config.JWKS_TTL_SECONDS
            if fresh and kid in self._keys:
                return self._keys[kid]
            may_fetch = now - self._attempted_at >= config.JWKS_MIN_REFETCH_SECONDS
            if may_fetch:
                self._attempted_at = now
                try:
                    keys = await asyncio.to_thread(
                        _fetch_jwks, config.get_auth_settings().jwks_url
                    )
                except Exception as exc:  # network, status, size or format problem
                    logger.warning("jwks_fetch_failed", error=type(exc).__name__)
                else:
                    if keys:
                        self._keys, self._fetched_at = keys, time.monotonic()
            if kid in self._keys:
                stale_for = time.monotonic() - self._fetched_at - config.JWKS_TTL_SECONDS
                if stale_for < config.JWKS_MAX_STALE_SECONDS:
                    return self._keys[kid]
                raise KeysUnavailableError("signing keys are too old and could not be refreshed")
            if not self._keys or time.monotonic() - self._fetched_at >= (
                config.JWKS_TTL_SECONDS + config.JWKS_MAX_STALE_SECONDS
            ):
                raise KeysUnavailableError("signing keys could not be loaded")
            raise InvalidTokenError("unknown signing key")


_cache = KeyCache()


def reset_key_cache() -> None:
    _cache.clear()


# --- verification -----------------------------------------------------------------------


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise InvalidTokenError(f"bad {name}")
    return float(value)


def check_claims(payload: dict[str, Any], *, issuer: str, now: float) -> VerifiedToken:
    """Validate the claims of a token whose signature has already been verified."""
    if payload.get("iss") != issuer:
        raise InvalidTokenError("wrong issuer")
    audience = payload.get("aud")
    audiences = [audience] if isinstance(audience, str) else audience
    if not isinstance(audiences, list) or config.API_CLIENT_ID not in audiences:
        raise InvalidTokenError("wrong audience")
    if payload.get("typ") != "Bearer":  # rejects ID tokens and refresh tokens
        raise InvalidTokenError("not an access token")
    leeway = config.CLOCK_LEEWAY_SECONDS
    if "exp" not in payload:
        raise InvalidTokenError("no expiry")
    if _number(payload["exp"], "exp") + leeway <= now:
        raise InvalidTokenError("expired")
    if "nbf" in payload and _number(payload["nbf"], "nbf") - leeway > now:
        raise InvalidTokenError("not yet valid")
    if "iat" in payload and _number(payload["iat"], "iat") - leeway > now:
        raise InvalidTokenError("issued in the future")
    sub = payload.get("sub")
    if not isinstance(sub, str) or not 0 < len(sub) <= _MAX_SUBJECT or not sub.isprintable():
        raise InvalidTokenError("bad subject")
    sid = payload.get("sid")
    auth_time = payload.get("auth_time")

    roles: tuple[str, ...] = ()
    access = payload.get("resource_access")
    if isinstance(access, dict):
        client = access.get(config.API_CLIENT_ID)
        listed = client.get("roles") if isinstance(client, dict) else None
        if isinstance(listed, list):
            roles = tuple(sorted({r for r in listed if isinstance(r, str)}))
    email = payload.get("email")
    name = payload.get("name") or payload.get("preferred_username")
    attributes = {
        field_name: coerce_attribute(kind, payload[field_name], max_length, allowed)
        for field_name, kind, max_length, allowed, _default in config.CUSTOM_FIELDS
        if field_name in payload
    }
    return VerifiedToken(
        sub=sub,
        issuer=issuer,
        sid=sid[:_MAX_SUBJECT] if isinstance(sid, str) and sid else None,
        auth_time=auth_time if isinstance(auth_time, int) and not isinstance(auth_time, bool) else None,
        email=email[:320] if isinstance(email, str) and email else None,
        email_verified=payload.get("email_verified") is True,
        name=name[:255] if isinstance(name, str) and name else None,
        roles=roles,
        organizations=_organizations(payload.get("organization")),
        attributes=attributes,
    )


_INT_RE = re.compile(r"^-?[0-9]{1,18}$")
_TEXT_FALLBACK = 255
_LONG_TEXT = 10_000


def coerce_attribute(kind: str, value: Any, max_length: int | None, allowed: tuple[str, ...]) -> Any:
    """A custom field's claim as the Python value its column holds, or None if it does not fit.
    Keycloak validates fields when a user is saved; this is the API's own check, so a value that
    slipped past it (or arrives as the wrong JSON type) can never break or poison a row."""
    if isinstance(value, list) and len(value) == 1:  # Keycloak may deliver a single value in a list
        value = value[0]
    try:
        match kind:
            case "string" | "text" | "email" | "phone" | "url":
                limit = max_length or (_LONG_TEXT if kind == "text" else _TEXT_FALLBACK)
                if not isinstance(value, str) or len(value) > limit or "\x00" in value:
                    return None
                return value
            case "integer":
                if isinstance(value, bool):
                    return None
                if isinstance(value, int):
                    return value
                return int(value) if isinstance(value, str) and _INT_RE.fullmatch(value) else None
            case "float":
                if isinstance(value, bool):
                    return None
                number = float(value) if isinstance(value, int | float | str) else math.nan
                return number if math.isfinite(number) else None
            case "boolean":
                if isinstance(value, bool):
                    return value
                return {"true": True, "false": False}.get(value) if isinstance(value, str) else None
            case "date":
                return dt.date.fromisoformat(value) if isinstance(value, str) else None
            case "datetime":
                if not isinstance(value, str):
                    return None
                moment = dt.datetime.fromisoformat(value)
                return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)
            case "enum":
                return value if isinstance(value, str) and value in allowed else None
    except (ValueError, OverflowError):
        return None
    return None


def _organizations(value: Any) -> tuple[str, ...]:
    """Aliases from the `organization` claim, whether Keycloak sends a list or an object."""
    if isinstance(value, dict):
        value = list(value)
    if not isinstance(value, list):
        return ()
    aliases = {a for a in value if isinstance(a, str) and 0 < len(a) <= 255}
    return tuple(sorted(aliases))


def _verify_signature(key: rsa.RSAPublicKey, signing_input: bytes, signature: bytes) -> None:
    try:
        key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature as exc:
        raise InvalidTokenError("bad signature") from exc


async def verify_access_token(token: str, *, now: float | None = None) -> VerifiedToken:
    """The verified claims of a Keycloak access token for this project's API client."""
    header, payload, signing_input, signature = parse(token)
    if header.get("alg") != _ALLOWED_ALG:
        raise InvalidTokenError("algorithm not allowed")
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid or len(kid) > 200:
        raise InvalidTokenError("missing key id")
    key = await _cache.key_for(kid)
    _verify_signature(key, signing_input, signature)
    return check_claims(
        payload,
        issuer=config.get_auth_settings().issuer,
        now=time.time() if now is None else now,
    )


_LOGOUT_EVENT = "http://schemas.openid.net/event/backchannel-logout"


@dataclass(frozen=True)
class LogoutToken:
    issuer: str
    sub: str | None
    sid: str | None


def check_logout_claims(payload: dict[str, Any], *, issuer: str, now: float) -> LogoutToken:
    """Validate a back-channel logout token (OpenID Connect Back-Channel Logout 1.0, section 2.6)
    whose signature has already been verified."""
    if payload.get("iss") != issuer:
        raise InvalidTokenError("wrong issuer")
    audience = payload.get("aud")
    audiences = [audience] if isinstance(audience, str) else audience
    wanted = {config.API_CLIENT_ID, config.WEB_CLIENT_ID}
    if not isinstance(audiences, list) or not wanted & set(audiences):
        raise InvalidTokenError("wrong audience")
    iat = _number(payload.get("iat"), "iat")
    if abs(now - iat) > 120 + config.CLOCK_LEEWAY_SECONDS:
        raise InvalidTokenError("logout token is not recent")
    if "exp" in payload and _number(payload["exp"], "exp") + config.CLOCK_LEEWAY_SECONDS <= now:
        raise InvalidTokenError("expired")
    events = payload.get("events")
    if not isinstance(events, dict) or _LOGOUT_EVENT not in events:
        raise InvalidTokenError("not a logout token")
    if "nonce" in payload:
        raise InvalidTokenError("a logout token must not carry a nonce")  # it would be an ID token
    if not isinstance(payload.get("jti"), str) or not payload["jti"]:
        raise InvalidTokenError("no jti")
    sub, sid = payload.get("sub"), payload.get("sid")
    sub = sub if isinstance(sub, str) and 0 < len(sub) <= _MAX_SUBJECT else None
    sid = sid if isinstance(sid, str) and 0 < len(sid) <= _MAX_SUBJECT else None
    if sub is None and sid is None:
        raise InvalidTokenError("neither sub nor sid")
    return LogoutToken(issuer=issuer, sub=sub, sid=sid)


async def verify_logout_token(token: str, *, now: float | None = None) -> LogoutToken:
    header, payload, signing_input, signature = parse(token)
    if header.get("alg") != _ALLOWED_ALG:
        raise InvalidTokenError("algorithm not allowed")
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid or len(kid) > 200:
        raise InvalidTokenError("missing key id")
    key = await _cache.key_for(kid)
    _verify_signature(key, signing_input, signature)
    return check_logout_claims(
        payload,
        issuer=config.get_auth_settings().issuer,
        now=time.time() if now is None else now,
    )


def logout_token_from_form(body: bytes) -> str:
    """The `logout_token` field of a form post (parsed by hand: no multipart library needed)."""
    fields = urllib.parse.parse_qs(body[: config.MAX_TOKEN_BYTES + 64].decode("utf-8", "replace"))
    values = fields.get("logout_token", [])
    if len(values) != 1 or not values[0] or len(values[0]) > config.MAX_TOKEN_BYTES:
        raise InvalidTokenError("no logout_token")
    return values[0]
