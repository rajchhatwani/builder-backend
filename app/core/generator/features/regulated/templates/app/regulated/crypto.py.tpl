"""Field encryption of regulated mode (generated): AES-256-GCM with a fresh random 12-byte nonce.

A stored value is `rg1:<keyid>:<urlsafe-base64(nonce + ciphertext + tag)>`. The additional authenticated data is
`<table>.<column>`, so a ciphertext moved to another column or table does not decrypt. (It does NOT bind the row:
two rows of the same column can swap values undetected; the row id is not part of the AAD.)

Decrypt picks the key by the id in the value. An unknown key id, a bad tag or a value that is not ciphertext
raises RegulatedError: it fails closed and never returns a partial or plaintext value.

The blind index is HMAC-SHA256 over the normalised (stripped, case-folded) value with a purpose-bound subkey: it lets
a `searchable` field answer an equality filter without the database seeing the value."""

import base64
import binascii
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.regulated import keys, settings
from app.regulated.errors import RegulatedError

PREFIX = "rg1"
_NONCE_BYTES = 12


def _aad(table: str, column: str) -> bytes:
    return f"{table}.{column}".encode()


def is_ciphertext(stored: str) -> bool:
    return stored.startswith(PREFIX + ":")


def key_id_of(stored: str) -> str | None:
    """The key id a stored value was encrypted under, or None when it is not ciphertext."""
    parts = stored.split(":", 2)
    return parts[1] if len(parts) == 3 and parts[0] == PREFIX else None


def encrypt(table: str, column: str, plaintext: str) -> str:
    ring = keys.get_ring()
    nonce = os.urandom(_NONCE_BYTES)
    sealed = AESGCM(ring.keys[ring.active_id]).encrypt(nonce, plaintext.encode(), _aad(table, column))
    return f"{PREFIX}:{ring.active_id}:{base64.urlsafe_b64encode(nonce + sealed).decode()}"


def decrypt(table: str, column: str, stored: str) -> str:
    parts = stored.split(":", 2)
    if len(parts) != 3 or parts[0] != PREFIX:
        raise RegulatedError(f"{table}.{column} holds a value that is not ciphertext")
    key = keys.get_ring().keys.get(parts[1])
    if key is None:
        raise RegulatedError(f"{table}.{column} was encrypted under a key that is not in the keyring")
    try:
        blob = base64.urlsafe_b64decode(parts[2] + "=" * (-len(parts[2]) % 4))
        if len(blob) < _NONCE_BYTES + 16:
            raise ValueError
        return AESGCM(key).decrypt(blob[:_NONCE_BYTES], blob[_NONCE_BYTES:], _aad(table, column)).decode()
    except (InvalidTag, binascii.Error, ValueError, UnicodeDecodeError):
        raise RegulatedError(f"{table}.{column} holds ciphertext that failed authentication") from None


def normalise(value: str) -> str:
    return value.strip().casefold()


def _bidx(table: str, column: str, value: str, key_id: str | None) -> str:
    key = keys.derive(f"blind-index:{table}.{column}", key_id)
    return hmac.new(key, normalise(value).encode(), hashlib.sha256).hexdigest()


def _require_searchable(table: str, column: str) -> None:
    rule = settings.PROTECTED.get(table, {}).get(column)
    if rule is None or not rule["searchable"]:
        raise RegulatedError(f"{table}.{column} is not searchable (no blind index)")


def blind_index(table: str, column: str, value: str, key_id: str | None = None) -> str:
    """The blind index of `value` under ring key `key_id` (default: the active key)."""
    _require_searchable(table, column)
    return _bidx(table, column, value, key_id)


def blind_indexes(table: str, column: str, value: str) -> list[str]:
    """The blind index under EVERY ring key, active first: rows not yet re-encrypted still match."""
    _require_searchable(table, column)
    ring = keys.get_ring()
    ids = [ring.active_id, *(k for k in ring.keys if k != ring.active_id)]
    return [_bidx(table, column, value, kid) for kid in ids]
