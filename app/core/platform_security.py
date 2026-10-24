"""Credential primitives for the builder's own accounts (not the generated projects').

Pure functions, stdlib plus `cryptography` (HKDF). Nothing here touches the database or HTTP.

Choices follow the OWASP cheat sheets for password storage and JWTs:
  - passwords: scrypt (N=2**15, r=8, p=1), random 16 byte salt, constant-time compare;
  - access tokens: HS256 JWT, 15 minutes, `alg` pinned (a token naming any other algorithm, `none`
    included, is rejected before the signature is looked at), `aud`, `iss`, `exp` always required;
  - refresh / API tokens: opaque random strings; only their SHA-256 is stored.
The JWT key is derived from SECRET_KEY with HKDF under its own label, so a leaked JWT key does not
reveal the key that encrypts stored credentials and vice versa.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ISSUER = "backend-builder"
AUDIENCE_APP = "builder-app"
AUDIENCE_ADMIN = "builder-admin"

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128  # scrypt cost grows with input only up to a block, but cap abuse anyway

# Tests lower this to keep the suite fast; production code never touches it.
SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SCRYPT_SALT_BYTES = 16

# Passwords that satisfy a length rule but are on every attacker's first list.
_COMMON_PASSWORDS = frozenset(
    {
        "password1234",
        "passwordpassword",
        "123456789012",
        "1234567890123",
        "qwertyuiopas",
        "qwertyuiop12",
        "iloveyou1234",
        "administrator",
        "letmein123456",
        "welcome12345",
        "changeme1234",
        "backendbuilder",
    }
)


# -- passwords ---------------------------------------------------------------------------


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=dklen,
        maxmem=256 * n * r,  # headroom over the 128*n*r the algorithm needs
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SCRYPT_SALT_BYTES)
    digest = _scrypt(password, salt, SCRYPT_N, _SCRYPT_R, _SCRYPT_P, _SCRYPT_DKLEN)
    return f"scrypt${SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check. Any malformed stored hash is simply a failed login."""
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = _unb64(digest)
        actual = _scrypt(password, _unb64(salt), int(n), int(r), int(p), len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


_DUMMY_HASH: str | None = None


def burn_password_check(password: str) -> None:
    """Spend the same time as a real check, for logins naming an unknown account."""
    global _DUMMY_HASH  # noqa: PLW0603
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("dummy-password-for-timing")
    verify_password(password, _DUMMY_HASH)


def password_problems(password: str, email: str = "") -> list[str]:
    """Human-readable reasons a password is refused (empty list = acceptable)."""
    problems: list[str] = []
    if len(password) < PASSWORD_MIN_LENGTH:
        problems.append(f"must be at least {PASSWORD_MIN_LENGTH} characters")
    if len(password) > PASSWORD_MAX_LENGTH:
        problems.append(f"must be at most {PASSWORD_MAX_LENGTH} characters")
    lowered = password.lower()
    local = email.split("@", 1)[0].lower()
    if (local and len(local) >= 4 and local in lowered) or lowered in _COMMON_PASSWORDS:
        problems.append("is too easy to guess (common word or contains your email name)")
    if len(set(password)) < 5:
        problems.append("needs more variety of characters")
    return problems


# -- opaque tokens -----------------------------------------------------------------------


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_refresh_token() -> tuple[str, str]:
    """(token, sha256-of-token). 256 bits of randomness; the hash is what gets stored."""
    token = "bb_rt_" + secrets.token_urlsafe(32)
    return token, hash_token(token)


API_TOKEN_PREFIX = "bb_pat_"
_API_TOKEN_RE = re.compile(r"^bb_pat_([A-Za-z0-9]{10})_([A-Za-z0-9_-]{43})$")


def new_api_token() -> tuple[str, str, str]:
    """(token, public lookup id, sha256-of-token). The token is shown once and never stored."""
    public_id = "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(10))
    token = f"{API_TOKEN_PREFIX}{public_id}_{secrets.token_urlsafe(32)}"
    return token, public_id, hash_token(token)


def parse_api_token(token: str) -> str | None:
    """The public lookup id of a well-formed API token, else None (never raises)."""
    match = _API_TOKEN_RE.match(token)
    return match.group(1) if match else None


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


# -- JWT (HS256) -------------------------------------------------------------------------

_JWT_LABEL = b"builder-platform-jwt-v1"
MIN_SECRET_LENGTH = 32
# Values shipped in docker-compose.yml / .env.example: fine on a laptop, never in production.
KNOWN_PLACEHOLDERS = ("local-development-only", "change-me", "changeme", "your-secret")


class TokenError(Exception):
    """Any reason a bearer token is unusable. The message is for logs, never for the client."""


_key_cache: tuple[str, bytes] | None = None


def signing_key() -> bytes:
    """HKDF(SECRET_KEY, label). Cached per distinct secret so tests can change SECRET_KEY."""
    global _key_cache  # noqa: PLW0603
    secret = os.environ.get("SECRET_KEY", "")
    if not secret:
        raise RuntimeError("SECRET_KEY is not set; the builder cannot sign tokens")
    if _key_cache is None or _key_cache[0] != secret:
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_JWT_LABEL).derive(
            secret.encode("utf-8")
        )
        _key_cache = (secret, key)
    return _key_cache[1]


def _sign(signing_input: bytes) -> str:
    return _b64(hmac.new(signing_key(), signing_input, hashlib.sha256).digest())


def encode_jwt(claims: dict[str, Any]) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    head = _b64(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
    body = _b64(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    signing_input = f"{head}.{body}".encode("ascii")
    return f"{head}.{body}.{_sign(signing_input)}"


def decode_jwt(
    token: str, *, audience: str, now: float | None = None, leeway: int = 30
) -> dict[str, Any]:
    """Verify and return the claims, or raise TokenError."""
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenError("malformed token")
    head_b64, body_b64, sig = parts
    try:
        header = json.loads(_unb64(head_b64))
        claims = json.loads(_unb64(body_b64))
    except (ValueError, TypeError) as exc:
        raise TokenError("malformed token") from exc
    if not isinstance(header, dict) or header.get("alg") != "HS256" or header.get("typ") != "JWT":
        raise TokenError("unsupported algorithm")
    if not isinstance(claims, dict):
        raise TokenError("malformed claims")
    expected = _sign(f"{head_b64}.{body_b64}".encode("ascii"))
    if not hmac.compare_digest(sig.encode("ascii", "ignore"), expected.encode("ascii")):
        raise TokenError("bad signature")
    current = time.time() if now is None else now
    exp, iat = claims.get("exp"), claims.get("iat")
    if not isinstance(exp, int | float) or not isinstance(iat, int | float):
        raise TokenError("missing exp/iat")
    if current > exp + leeway:
        raise TokenError("expired")
    if iat > current + leeway:
        raise TokenError("issued in the future")
    if claims.get("iss") != ISSUER:
        raise TokenError("wrong issuer")
    if claims.get("aud") != audience:
        raise TokenError("wrong audience")
    if not isinstance(claims.get("sub"), str):
        raise TokenError("missing subject")
    return claims


def access_claims(
    *, user_id: str, audience: str, token_version: int, ttl_seconds: int, now: float | None = None
) -> dict[str, Any]:
    issued = int(time.time() if now is None else now)
    return {
        "iss": ISSUER,
        "aud": audience,
        "sub": user_id,
        "iat": issued,
        "exp": issued + ttl_seconds,
        "jti": secrets.token_hex(8),
        "tv": token_version,
    }


def check_secret_strength(secret: str, environment: str) -> str | None:
    """None if SECRET_KEY is usable here, else the reason it is not. `local` is lenient."""
    if environment == "local":
        return None if secret else "SECRET_KEY is not set"
    if len(secret) < MIN_SECRET_LENGTH:
        return f"SECRET_KEY must be at least {MIN_SECRET_LENGTH} characters outside `local`"
    if len(set(secret)) < 10:
        return "SECRET_KEY has too little variety; generate it with `openssl rand -base64 48`"
    if any(marker in secret.lower() for marker in KNOWN_PLACEHOLDERS):
        return "SECRET_KEY is a placeholder from the docs or docker-compose; generate a real one"
    return None
