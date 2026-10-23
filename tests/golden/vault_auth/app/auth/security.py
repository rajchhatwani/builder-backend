"""Password hashing, JWT access tokens and one-time secrets.

Passwords, tokens and codes use the standard library only. Access tokens are signed
with RS256, which needs the `cryptography` package."""

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from functools import lru_cache
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

# scrypt cost: n=2**15, r=8, p=1 needs ~32 MiB and takes tens of milliseconds.
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024
_SALT_BYTES = 16
_KEY_BYTES = 32
_JWT_HEADER = {"alg": 'RS256', "typ": "JWT"}


class InvalidTokenError(Exception):
    """The token is malformed, forged, expired or of the wrong type."""


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# --- passwords --------------------------------------------------------------------------


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        maxmem=_SCRYPT_MAXMEM,
        dklen=_KEY_BYTES,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64e(salt)}${_b64e(key)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt":
            return False
        key = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_b64d(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            maxmem=_SCRYPT_MAXMEM,
            dklen=_KEY_BYTES,
        )
        return hmac.compare_digest(key, _b64d(expected))
    except (ValueError, TypeError):
        return False


# Verified against when the account does not exist, so login time does not reveal it.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))


# --- JWT (RS256) ----------------------------------------------------------------
# `key` is the RSA private key in PEM form. Tokens are verified with its public half, so
# other services can verify them with only the public key (see the JWKS route).


@lru_cache(maxsize=4)
def _private_key(pem: str) -> rsa.RSAPrivateKey:
    key = serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
        raise ValueError("AUTH_JWT_PRIVATE_KEY must be an RSA private key of at least 2048 bits")
    return key


def _sign(signing_input: bytes, key: str) -> str:
    signature = _private_key(key).sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return _b64e(signature)


def _verify(signing_input: bytes, signature: str, key: str) -> None:
    try:
        _private_key(key).public_key().verify(
            _b64d(signature), signing_input, padding.PKCS1v15(), hashes.SHA256()
        )
    except (InvalidSignature, ValueError) as exc:
        raise InvalidTokenError("bad signature") from exc


def public_jwk(key: str) -> dict[str, str]:
    """The public half of `key` as a JSON Web Key, for the JWKS route."""
    numbers = _private_key(key).public_key().public_numbers()

    def to_b64(value: int) -> str:
        return _b64e(value.to_bytes((value.bit_length() + 7) // 8, "big"))

    return {"kty": "RSA", "use": "sig", "alg": "RS256", "n": to_b64(numbers.n), "e": to_b64(numbers.e)}


def generate_private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")


def encode_jwt(claims: dict[str, Any], key: str) -> str:
    header = _b64e(json.dumps(_JWT_HEADER, separators=(",", ":")).encode("ascii"))
    payload = _b64e(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header}.{payload}".encode("ascii")
    return f"{header}.{payload}.{_sign(signing_input, key)}"


def decode_jwt(token: str, key: str, *, now: float | None = None) -> dict[str, Any]:
    """Verify signature, algorithm and expiry. Raises InvalidTokenError otherwise."""
    try:
        header_part, payload_part, signature = token.split(".")
        header = json.loads(_b64d(header_part))
        # Only the configured algorithm is accepted: no "none", no algorithm confusion.
        if header != _JWT_HEADER:
            raise InvalidTokenError("unsupported token header")
        _verify(f"{header_part}.{payload_part}".encode("ascii"), signature, key)
        claims = json.loads(_b64d(payload_part))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise InvalidTokenError("malformed token") from exc
    if not isinstance(claims, dict):
        raise InvalidTokenError("malformed token")
    exp = claims.get("exp")
    if not isinstance(exp, int | float) or exp <= (time.time() if now is None else now):
        raise InvalidTokenError("token expired")
    return claims


def create_access_token(
    user_id: uuid.UUID,
    roles: list[str],
    *,
    key: str,
    ttl_seconds: int,
    tenant_id: uuid.UUID | None = None,
) -> str:
    issued = int(time.time())
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "roles": roles,
        "type": "access",
        "iat": issued,
        "exp": issued + ttl_seconds,
        "jti": uuid.uuid4().hex,
    }
    if tenant_id is not None:
        claims["tid"] = str(tenant_id)  # for services that only check the token
    return encode_jwt(claims, key)


# --- one-time secrets -------------------------------------------------------------------


def new_token() -> str:
    """A URL-safe secret with 256 bits of entropy (refresh tokens, email links)."""
    return secrets.token_urlsafe(32)


def new_otp() -> str:
    """A six-digit code for SMS."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_secret(value: str) -> str:
    """Only hashes of tokens and codes are stored, so a database leak cannot be replayed."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
