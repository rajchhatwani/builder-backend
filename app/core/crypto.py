"""Symmetric encryption utilities for storing sensitive credentials at rest.

Design:
  - Uses Fernet (AES-128-CBC + HMAC-SHA256) from the `cryptography` library.
  - The Fernet key is derived from the application's SECRET_KEY via HKDF-SHA256,
    scoped to "builder-auth-secrets" so that rotating SECRET_KEY or changing the
    label invalidates all previously encrypted values without touching the key
    derivation algorithm.
  - Encrypt/decrypt are synchronous (CPU-bound, μs-scale) — no async needed.
  - A None plaintext round-trips as None (convenience for optional fields).

P6: keys come from a KeyProvider (app.core.key_provider). New ciphertext is
`v2:<keyid>:<fernet token>`; un-prefixed legacy tokens still decrypt (env provider: key env0; other
providers: tried against every key in the ring). `reencrypt_all` moves stored rows to the active key.

Usage:
    from app.core.crypto import encrypt, decrypt

    ciphertext = encrypt("s3cr3t")   # returns URL-safe base64 string
    plaintext  = decrypt(ciphertext) # returns original string
"""

import base64
import os
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.key_provider import KeyProvider, KeyRing, build_provider

from cryptography.fernet import Fernet, InvalidToken
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


# ── Key ring (P6) ─────────────────────────────────────────────────────────────

PREFIX = "v2:"
_provider: KeyProvider | None = None
_ring: KeyRing | None = None


def configure(provider: KeyProvider | None) -> None:
    """Install a provider (tests, FakeKms) or None to fall back to the configured one."""
    global _provider, _ring  # noqa: PLW0603
    _provider, _ring = provider, None


def reset() -> None:
    configure(None)


def _get_ring() -> KeyRing:
    global _ring  # noqa: PLW0603
    # `_fernet is None` also means "SECRET_KEY may have changed": rebuild an env-derived ring.
    if _ring is not None and not (_fernet is None and "env0" in _ring.keys):
        return _ring
    provider = _provider
    if provider is None:
        from app.config import get_settings  # noqa: PLC0415 - config imports nothing from here

        s = get_settings()
        provider = build_provider(
            s.key_provider,
            path=s.key_provider_file,
            command=s.key_provider_command,
            command_env=s.key_provider_command_env,
            env_fernet=lambda: _get_fernet(),
        )
    _ring = provider.load()
    return _ring


def active_key_id() -> str:
    return _get_ring().active_id


def key_id_of(ciphertext: str) -> str | None:
    """The key id embedded in a v2 token (None for a legacy token)."""
    if ciphertext.startswith(PREFIX):
        parts = ciphertext.split(":", 2)
        if len(parts) == 3:
            return parts[1]
    return None


# ── Public API ────────────────────────────────────────────────────────────────


def encrypt(plaintext: str | None) -> str | None:
    """Encrypt *plaintext* with the active key and return `v2:<keyid>:<fernet token>`.

    Returns None if *plaintext* is None (field not configured).
    """
    if plaintext is None:
        return None
    ring = _get_ring()
    token = ring.keys[ring.active_id].encrypt(plaintext.encode()).decode()
    return f"{PREFIX}{ring.active_id}:{token}"


def decrypt(ciphertext: str | None) -> str | None:
    """Decrypt a token produced by :func:`encrypt` (or a legacy un-prefixed Fernet token).

    Returns None if *ciphertext* is None (field not configured).
    Raises ``cryptography.fernet.InvalidToken`` if the token is tampered with, names an unknown
    key id, or was encrypted with a different key — treat this as a 500.
    """
    if ciphertext is None:
        return None
    ring = _get_ring()
    if ciphertext.startswith(PREFIX):
        parts = ciphertext.split(":", 2)
        if len(parts) != 3 or parts[1] not in ring.keys:
            raise InvalidToken
        return ring.keys[parts[1]].decrypt(parts[2].encode()).decode()
    # legacy token: env provider -> env0 only; otherwise any key the operator put in the ring
    for kid in ["env0"] if "env0" in ring.keys else list(ring.keys):
        try:
            return ring.keys[kid].decrypt(ciphertext.encode()).decode()
        except InvalidToken:
            continue
    raise InvalidToken


# ── Rotation ──────────────────────────────────────────────────────────────────

# Every column that stores ciphertext: (table, column, is_bytes). Keep in sync with the models;
# tests/unit/test_key_rotation.py greps the models for `_enc` / secret columns to catch drift.
CIPHERTEXT_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    ("project_auth_secrets", "smtp_username", False),
    ("project_auth_secrets", "smtp_password", False),
    ("project_auth_secrets", "twilio_account_sid", False),
    ("project_auth_secrets", "twilio_auth_token", False),
    ("project_auth_secrets", "vonage_api_key", False),
    ("project_auth_secrets", "vonage_api_secret", False),
    ("project_auth_secrets", "aws_access_key_id", False),
    ("project_auth_secrets", "aws_secret_access_key", False),
    ("project_auth_secrets", "aws_region", False),
    ("ai_org_settings", "api_key_enc", False),
    ("platform_users", "totp_secret_enc", False),
    ("sso_connections", "oidc_client_secret_enc", True),
)


def reencrypt_value(value: str) -> str | None:
    """The same plaintext under the active key, or None when it already uses it."""
    if key_id_of(value) == active_key_id():
        return None
    plain = decrypt(value)
    return encrypt(plain)


async def reencrypt_all(
    session: AsyncSession, columns: Sequence[tuple[str, str, bool]] = CIPHERTEXT_COLUMNS
) -> dict[str, int]:
    """Move every stored ciphertext to the active key. Idempotent; commit is the caller's.
    A row that does not decrypt aborts the run (nothing is overwritten with garbage)."""
    done: dict[str, int] = {}
    for table, column, is_bytes in columns:
        rows = (
            await session.execute(
                text(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL")  # noqa: S608
            )
        ).all()
        n = 0
        for rid, raw in rows:
            value = raw.decode() if is_bytes else raw
            new = reencrypt_value(value)
            if new is None:
                continue
            await session.execute(
                text(f"UPDATE {table} SET {column} = :v WHERE id = :id"),  # noqa: S608
                {"v": new.encode() if is_bytes else new, "id": rid},
            )
            n += 1
        done[f"{table}.{column}"] = n
    return done
