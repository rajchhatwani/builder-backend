"""The per-tenant credential vault (generated).

Envelope encryption with AES-256-GCM: every secret gets its own random data key; the data key is
wrapped by a key-encryption key derived (HKDF-SHA256) from the master key `PROVIDER_VAULT_KEY`. The
tenant, provider and key name are bound in as authenticated data, so a ciphertext copied to another
tenant's row (or renamed) fails to decrypt. Secrets are write-only: nothing here returns one except
`load`, which only the adapter call path (app/providers/client.py) uses.
"""

import base64
import datetime as _dt
import hashlib
import hmac
import os
import re
import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy.ext.asyncio import AsyncSession

from app.models._base import utcnow
from app.providers import config, logsafe
from app.providers.base import Credentials
from app.providers.errors import CredentialNotFound, VaultError
from app.providers.models import ProviderCredential

NIL_TENANT = uuid.UUID(int=0)  # the tenant of a project that is not multi-tenant
MAX_SECRET_LENGTH = 4096
NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_FORMAT = b"\x01"
_NONCE = 12


@dataclass(frozen=True)
class CredentialMeta:
    """What a listing may show: names, a fingerprint (not the value) and dates."""

    provider: str
    key_name: str
    fingerprint: str
    key_version: int
    created_at: _dt.datetime
    rotated_at: _dt.datetime | None


def _kek(master: str, version: int) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=f"provider-vault-kek-v{version}".encode()
    ).derive(master.encode())


def _aad(tenant_id: uuid.UUID, provider: str, key_name: str) -> bytes:
    return f"{tenant_id}|{provider}|{key_name}".encode()


def fingerprint(master: str, version: int, aad: bytes, value: str) -> str:
    """A short, non-reversible tag to tell two secrets apart (HMAC with a derived key, bound to the tenant)."""
    key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=f"provider-vault-fp-v{version}".encode()
    ).derive(master.encode())
    return hmac.new(key, aad + b"\x00" + value.encode(), hashlib.sha256).hexdigest()[:10]


def encrypt(master: str, version: int, aad: bytes, value: str) -> str:
    data_key = AESGCM.generate_key(bit_length=256)
    wrap_nonce, nonce = os.urandom(_NONCE), os.urandom(_NONCE)
    wrapped = AESGCM(_kek(master, version)).encrypt(wrap_nonce, data_key, aad)
    body = AESGCM(data_key).encrypt(nonce, value.encode(), aad)
    return base64.urlsafe_b64encode(_FORMAT + wrap_nonce + bytes([len(wrapped)]) + wrapped + nonce + body).decode()


def decrypt(master: str, version: int, aad: bytes, ciphertext: str) -> str:
    try:
        raw = base64.urlsafe_b64decode(ciphertext.encode())
        if raw[:1] != _FORMAT:
            raise ValueError("format")
        wrap_nonce = raw[1 : 1 + _NONCE]
        size = raw[1 + _NONCE]
        start = 2 + _NONCE
        wrapped = raw[start : start + size]
        nonce = raw[start + size : start + size + _NONCE]
        body = raw[start + size + _NONCE :]
        data_key = AESGCM(_kek(master, version)).decrypt(wrap_nonce, wrapped, aad)
        return AESGCM(data_key).decrypt(nonce, body, aad).decode()
    except (InvalidTag, ValueError, IndexError):
        # Never say which: a wrong key, a tampered row and another tenant's row look the same.
        raise VaultError("a stored credential cannot be decrypted") from None


def _check_names(provider: str, key_name: str) -> None:
    if not NAME_RE.fullmatch(provider) or not NAME_RE.fullmatch(key_name):
        raise VaultError("provider and key names are lowercase letters, digits and underscores")


def _meta(row: ProviderCredential) -> CredentialMeta:
    return CredentialMeta(
        provider=row.provider,
        key_name=row.key_name,
        fingerprint=row.fingerprint,
        key_version=row.key_version,
        created_at=row.created_at,
        rotated_at=row.rotated_at,
    )


def _scope(tenant_id: uuid.UUID) -> sa.ColumnElement[bool]:
    return ProviderCredential.tenant_id == tenant_id


async def put(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    provider: str,
    key_name: str,
    value: str,
    created_by: uuid.UUID | None,
) -> CredentialMeta:
    """Store (or replace) one secret of this tenant. The value is encrypted before it is staged."""
    _check_names(provider, key_name)
    if not value or len(value) > MAX_SECRET_LENGTH:
        raise VaultError(f"a credential is 1 to {MAX_SECRET_LENGTH} characters")
    version, keys = config.vault_keys()
    master = keys[version]
    aad = _aad(tenant_id, provider, key_name)
    ciphertext = encrypt(master, version, aad, value)
    tag = fingerprint(master, version, aad, value)
    row = (
        await session.execute(
            sa.select(ProviderCredential).where(
                _scope(tenant_id),
                ProviderCredential.provider == provider,
                ProviderCredential.key_name == key_name,
            )
        )
    ).scalar_one_or_none()
    now = utcnow()
    if row is None:
        row = ProviderCredential(
            tenant_id=tenant_id,
            provider=provider,
            key_name=key_name,
            ciphertext=ciphertext,
            key_version=version,
            fingerprint=tag,
            created_at=now,
            created_by=created_by,
        )
        session.add(row)
    else:
        row.ciphertext, row.key_version, row.fingerprint, row.rotated_at = ciphertext, version, tag, now
    await session.flush()
    return _meta(row)


async def delete(session: AsyncSession, tenant_id: uuid.UUID, provider: str, key_name: str) -> bool:
    result = await session.execute(
        sa.delete(ProviderCredential).where(
            _scope(tenant_id),
            ProviderCredential.provider == provider,
            ProviderCredential.key_name == key_name,
        )
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def list_credentials(
    session: AsyncSession, tenant_id: uuid.UUID, provider: str | None = None
) -> list[CredentialMeta]:
    stmt = sa.select(ProviderCredential).where(_scope(tenant_id))
    if provider is not None:
        stmt = stmt.where(ProviderCredential.provider == provider)
    rows = (await session.execute(stmt.order_by(ProviderCredential.provider, ProviderCredential.key_name))).scalars()
    return [_meta(r) for r in rows]


async def has_credentials(session: AsyncSession, tenant_id: uuid.UUID, provider: str) -> bool:
    found = await session.execute(
        sa.select(ProviderCredential.id).where(_scope(tenant_id), ProviderCredential.provider == provider).limit(1)
    )
    return found.first() is not None


async def load(session: AsyncSession, tenant_id: uuid.UUID, provider: str) -> Credentials:
    """Decrypt this tenant's credentials of one provider. ONLY the adapter call path may use this."""
    rows = list(
        (
            await session.execute(
                sa.select(ProviderCredential).where(_scope(tenant_id), ProviderCredential.provider == provider)
            )
        ).scalars()
    )
    if not rows:
        raise CredentialNotFound("no credentials stored for this provider")
    _, keys = config.vault_keys()
    values: dict[str, str] = {}
    for row in rows:
        master = keys.get(row.key_version)
        if master is None:
            raise VaultError("a stored credential uses a key version that is no longer configured")
        values[row.key_name] = decrypt(master, row.key_version, _aad(tenant_id, row.provider, row.key_name), row.ciphertext)
    logsafe.register(values)
    return Credentials(values)


async def reencrypt_all(session: AsyncSession) -> int:
    """Move every credential to the current key version. Returns how many rows changed."""
    version, keys = config.vault_keys()
    changed = 0
    rows = (await session.execute(sa.select(ProviderCredential).where(ProviderCredential.key_version != version))).scalars()
    for row in list(rows):
        master = keys.get(row.key_version)
        if master is None:
            raise VaultError("a stored credential uses a key version that is no longer configured")
        aad = _aad(row.tenant_id, row.provider, row.key_name)
        value = decrypt(master, row.key_version, aad, row.ciphertext)
        row.ciphertext = encrypt(keys[version], version, aad, value)
        row.fingerprint = fingerprint(keys[version], version, aad, value)
        row.key_version, row.rotated_at = version, utcnow()
        changed += 1
    await session.flush()
    return changed
