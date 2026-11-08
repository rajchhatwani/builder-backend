"""Webhook signatures (generated): the Standard Webhooks scheme, HMAC-SHA256 over the RAW body.

    webhook-id:         the delivery id (one per delivery, the same on every retry: receivers dedupe on it)
    webhook-timestamp:  unix seconds when this attempt was signed
    webhook-signature:  `v1,<base64 hmac>`; several space-separated signatures while a secret is being rotated

    signed content = "<id>.<timestamp>.<raw body>"   key = base64 decode of the part after `whsec_`

Verification compares in constant time against EVERY candidate secret and signature (no early exit), checks
the timestamp against a tolerance (old AND far-future are refused), and refuses anything malformed.
"""

import base64
import binascii
import hashlib
import hmac
import secrets
import time

PREFIX = "whsec_"
HEADER_ID = "webhook-id"
HEADER_TIMESTAMP = "webhook-timestamp"
HEADER_SIGNATURE = "webhook-signature"
MAX_SIGNATURE_HEADER = 2048
MAX_ID_LENGTH = 128
MAX_SIGNATURES = 8
# A delivery id is part of the signed text "<id>.<timestamp>.<body>": it may not contain "." (or anything
# outside this set), or the split between id, timestamp and body would be ambiguous.
ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-:")


def valid_id(delivery_id: str) -> bool:
    return 0 < len(delivery_id) <= MAX_ID_LENGTH and all(c in ID_CHARS for c in delivery_id)


def new_secret() -> str:
    """A fresh signing secret: `whsec_` + 32 random bytes in base64."""
    return PREFIX + base64.b64encode(secrets.token_bytes(32)).decode()


def key_bytes(secret: str) -> bytes:
    """The HMAC key of a secret: the decoded part after `whsec_` (any other secret is used as UTF-8 text)."""
    if secret.startswith(PREFIX):
        try:
            return base64.b64decode(secret[len(PREFIX) :], validate=True)
        except (binascii.Error, ValueError):
            pass
    return secret.encode("utf-8")


def _mac(secret: str, delivery_id: str, timestamp: int, body: bytes) -> bytes:
    content = f"{delivery_id}.{timestamp}.".encode() + body
    return hmac.new(key_bytes(secret), content, hashlib.sha256).digest()


def sign(secret: str, delivery_id: str, timestamp: int, body: bytes) -> str:
    return "v1," + base64.b64encode(_mac(secret, delivery_id, timestamp, body)).decode()


def signature_header(secrets_in_use: list[str], delivery_id: str, timestamp: int, body: bytes) -> str:
    """All valid signatures, newest secret first (during a rotation: the new and the old one)."""
    return " ".join(sign(s, delivery_id, timestamp, body) for s in secrets_in_use)


def verify(
    header: str | None,
    delivery_id: str | None,
    timestamp: str | None,
    body: bytes,
    candidate_secrets: list[str],
    *,
    tolerance_seconds: int,
    now: float | None = None,
) -> bool:
    """True only for a fresh, well-formed request signed with one of `candidate_secrets`. Never raises."""
    if not header or not delivery_id or not timestamp or not candidate_secrets:
        return False
    if len(header) > MAX_SIGNATURE_HEADER or not valid_id(delivery_id):
        return False
    if not timestamp.isascii() or not timestamp.isdigit() or len(timestamp) > 12:
        return False
    stamp = int(timestamp)
    if abs((time.time() if now is None else now) - stamp) > tolerance_seconds:
        return False
    given: list[bytes] = []
    for part in header.split():
        version, _, value = part.partition(",")
        if version != "v1":
            continue
        try:
            given.append(base64.b64decode(value, validate=True))
        except (binascii.Error, ValueError):
            continue
        if len(given) >= MAX_SIGNATURES:
            break
    ok = False
    for secret in candidate_secrets:
        expected = _mac(secret, delivery_id, stamp, body)
        for candidate in given:
            if hmac.compare_digest(expected, candidate):
                ok = True  # keep comparing: the time taken does not depend on which one matched
    return ok
