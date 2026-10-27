"""Time-based one-time passwords (RFC 6238 over RFC 4226 HOTP), for built-in MFA (§4.4).

SHA-1, 6 digits, 30-second steps: the defaults every authenticator app understands. A code is
accepted for the current step and one step either side (clock drift), and never for a step at or
before the last one the account used, so a code cannot be replayed.
"""

import base64
import hashlib
import hmac
import re
import secrets
import struct
import time
import urllib.parse

PERIOD = 30
DIGITS = 6
DRIFT_STEPS = 1
_CODE_RE = re.compile(r"^\d{6}$")
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i


def new_secret() -> str:
    """160 random bits, base32 (the RFC 4226 recommended length)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def _key(secret: str) -> bytes:
    padded = secret.strip().replace(" ", "").upper()
    padded += "=" * (-len(padded) % 8)
    return base64.b32decode(padded)


def _hotp(key: bytes, counter: int, digits: int) -> str:
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10**digits)).zfill(digits)


def code_at(secret: str, at: float, *, digits: int = DIGITS) -> str:
    return _hotp(_key(secret), int(at) // PERIOD, digits)


def verify(
    secret: str, code: str, *, now: float | None = None, last_step: int | None = None
) -> int | None:
    """The time step the code belongs to, or None. Constant-time per candidate."""
    if not isinstance(code, str):
        return None
    code = code.replace(" ", "")
    if not _CODE_RE.match(code):
        return None
    key = _key(secret)
    current = int(time.time() if now is None else now) // PERIOD
    found: int | None = None
    for step in range(current - DRIFT_STEPS, current + DRIFT_STEPS + 1):
        if hmac.compare_digest(_hotp(key, step, DIGITS), code) and found is None:
            found = step
    if found is None or (last_step is not None and found <= last_step):
        return None
    return found


def otpauth_uri(secret: str, *, account: str, issuer: str) -> str:
    """The `otpauth://` URI authenticator apps read from a QR code."""
    label = urllib.parse.quote(f"{issuer}:{account}", safe="@:")
    query = urllib.parse.urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": DIGITS,
            "period": PERIOD,
        }
    )
    return f"otpauth://totp/{label}?{query}"


def new_recovery_codes(count: int = 10) -> list[str]:
    """One-time backup codes shown once, like `abcde-fghjk` (50 bits each)."""
    codes: set[str] = set()
    while len(codes) < count:
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        codes.add(f"{raw[:5]}-{raw[5:]}")
    return sorted(codes)


def normalize_recovery_code(code: str) -> str:
    return code.strip().lower().replace("-", "").replace(" ", "")
