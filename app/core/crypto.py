"""Symmetric encryption utilities for storing sensitive credentials at rest.

Design:
  - Uses Fernet (AES-128-CBC + HMAC-SHA256) from the `cryptography` library.
  - The Fernet key is derived from the application's SECRET_KEY via HKDF-SHA256,
    scoped to "builder-auth-secrets" so that rotating SECRET_KEY or changing the
    label invalidates all previously encrypted values without touching the key
    derivation algorithm.
  - Encrypt/decrypt are synchronous (CPU-bound, μs-scale) — no async needed.
  - A None plaintext round-trips as None (convenience for optional fields).

Usage:
    from app.core.crypto import encrypt, decrypt

    ciphertext = encrypt("s3cr3t")   # returns URL-safe base64 string
    plaintext  = decrypt(ciphertext) # returns original string
"""

import base64
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# ── Key derivation ────────────────────────────────────────────────────────────

_LABEL = b"builder-auth-secrets-v1"
_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """Lazily derive and cache the Fernet instance.

    The key is derived once per process from SECRET_KEY (must be set).
    Using HKDF means we get a proper 32-byte key regardless of the length
    or entropy of SECRET_KEY.
    """
    global _fernet  # noqa: PLW0603
    if _fernet is None:
        secret = os.environ.get("SECRET_KEY", "").encode()
        if not secret:
            raise RuntimeError(
                "SECRET_KEY environment variable is not set; "
                "cannot encrypt or decrypt auth credentials"
            )
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=_LABEL,
        )
        raw_key = hkdf.derive(secret)
        fernet_key = base64.urlsafe_b64encode(raw_key)
        _fernet = Fernet(fernet_key)
    return _fernet


# ── Public API ────────────────────────────────────────────────────────────────


def encrypt(plaintext: str | None) -> str | None:
    """Encrypt *plaintext* and return a URL-safe base64 Fernet token.

    Returns None if *plaintext* is None (field not configured).
    """
    if plaintext is None:
        return None
    token: bytes = _get_fernet().encrypt(plaintext.encode())
    return token.decode()


def decrypt(ciphertext: str | None) -> str | None:
    """Decrypt a Fernet token produced by :func:`encrypt`.

    Returns None if *ciphertext* is None (field not configured).
    Raises ``cryptography.fernet.InvalidToken`` if the token is tampered
    with or was encrypted with a different key — treat this as a 500.
    """
    if ciphertext is None:
        return None
    return _get_fernet().decrypt(ciphertext.encode()).decode()
