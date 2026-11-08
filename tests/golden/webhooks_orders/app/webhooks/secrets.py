"""Webhook secrets in the credential vault (generated). A secret is written once (the API returns it a single
time, on creation or rotation) and read back only here, by the code that signs or verifies.

Rotation without downtime: a new version becomes the current one and the old one stays valid for the overlap
window. Outgoing deliveries are signed with BOTH (receivers accept either); incoming requests are verified
against BOTH. After the window the old version is no longer used and is deleted by the next rotation."""

import datetime as _dt
import uuid
from collections.abc import Callable
from typing import Protocol

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import redact
from app.providers import config as vault_config
from app.providers import vault
from app.providers.models import ProviderCredential
from app.webhooks import signing

PROVIDER = "webhooks"


class Versioned(Protocol):
    secret_version: int
    previous_version: int | None
    previous_expires_at: _dt.datetime | None


def tenant_key(tenant_id: uuid.UUID | None) -> uuid.UUID:
    return tenant_id or vault.NIL_TENANT


def out_name(subscription_id: uuid.UUID, version: int) -> str:
    return f"out_{subscription_id.hex}_v{version}"


def in_name(endpoint: str, version: int) -> str:
    return f"in_{endpoint}_v{version}"


async def put(session: AsyncSession, tenant_id: uuid.UUID | None, key_name: str, value: str, by: uuid.UUID | None) -> None:
    await vault.put(session, tenant_key(tenant_id), PROVIDER, key_name, value, by)


async def delete(session: AsyncSession, tenant_id: uuid.UUID | None, key_name: str) -> None:
    await vault.delete(session, tenant_key(tenant_id), PROVIDER, key_name)


async def get(session: AsyncSession, tenant_id: uuid.UUID | None, key_name: str) -> str | None:
    """The secret, or None when it is not stored. A secret that cannot be decrypted raises VaultError."""
    tenant = tenant_key(tenant_id)
    row = (
        await session.execute(
            sa.select(ProviderCredential).where(
                ProviderCredential.tenant_id == tenant,
                ProviderCredential.provider == PROVIDER,
                ProviderCredential.key_name == key_name,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    _, keys = vault_config.vault_keys()
    master = keys.get(row.key_version)
    if master is None:
        raise vault.VaultError("a stored credential uses a key version that is no longer configured")
    value = vault.decrypt(master, row.key_version, vault._aad(tenant, PROVIDER, key_name), row.ciphertext)
    redact.register_secret(value)
    return value


def live_versions(row: Versioned, now: _dt.datetime) -> list[int]:
    """Current version first, then the previous one while its overlap window is open."""
    versions = [row.secret_version]
    if row.previous_version is not None and row.previous_expires_at is not None and row.previous_expires_at > now:
        versions.append(row.previous_version)
    return versions


async def rotate(
    session: AsyncSession,
    row: Versioned,
    tenant_id: uuid.UUID | None,
    name_of: Callable[[int], str],
    new_value: str,
    overlap_hours: int,
    now: _dt.datetime,
    by: uuid.UUID | None,
) -> None:
    """Store `new_value` as the next version; the old current version stays valid for `overlap_hours`."""
    if row.previous_version is not None:
        await delete(session, tenant_id, name_of(row.previous_version))  # an older overlap is over now
    newest = max(row.secret_version, row.previous_version or 0) + 1
    await put(session, tenant_id, name_of(newest), new_value, by)
    row.previous_version = row.secret_version
    row.previous_expires_at = now + _dt.timedelta(hours=overlap_hours)
    row.secret_version = newest


def fresh_secret() -> str:
    return signing.new_secret()
