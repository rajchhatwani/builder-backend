"""Idempotency keys for our own payment endpoints (generated).

A client that retries a request (timeout, double click, flaky network) must never create a second
payment or refund. The key is scoped to the tenant, the user and the route, and only a hash of it is
stored. Claiming a key inserts a row in the SAME transaction that creates the resource, so a
concurrent retry waits on the database's unique index and then finds the finished result.
"""

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.payments import config
from app.payments.models import IdempotencyKey

_KEY_RE = re.compile(r"[A-Za-z0-9_.:-]{8,128}")


def validate_key(raw: str | None) -> str:
    """The Idempotency-Key header is required on every request that moves money."""
    if raw is None or not _KEY_RE.fullmatch(raw):
        raise AppError(
            "idempotency_key_required",
            "send an Idempotency-Key header of 8 to 128 characters (letters, digits, _ . : -)",
            400,
        )
    return raw


def scope_hash(tenant_id: uuid.UUID | None, user_id: uuid.UUID, route: str, key: str) -> str:
    material = f"{tenant_id or '-'}|{user_id}|{route}|{key}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def request_hash(body: dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Claim:
    fresh: bool  # True: this request owns the key and must create the resource
    resource_id: uuid.UUID | None  # set when an earlier request already created it


async def claim(
    session: AsyncSession, *, scope: str, req_hash: str, resource_type: str
) -> Claim:
    """Take the key, or report what the earlier request with the same key did."""
    expires = datetime.now(UTC) + timedelta(hours=config.IDEMPOTENCY_TTL_HOURS)
    inserted = (
        await session.execute(
            insert(IdempotencyKey)
            .values(
                id=uuid.uuid4(),
                scope_hash=scope,
                request_hash=req_hash,
                resource_type=resource_type,
                created_at=datetime.now(UTC),
                expires_at=expires,
            )
            .on_conflict_do_nothing(index_elements=["scope_hash"])
            .returning(IdempotencyKey.id)
        )
    ).first()
    if inserted is not None:
        return Claim(fresh=True, resource_id=None)

    existing = (
        await session.execute(
            sa.select(IdempotencyKey).where(IdempotencyKey.scope_hash == scope).with_for_update()
        )
    ).scalar_one()
    if existing.expires_at <= datetime.now(UTC):
        # An expired key is free again: start over under the same row.
        existing.request_hash = req_hash
        existing.resource_type = resource_type
        existing.resource_id = None
        existing.created_at = datetime.now(UTC)
        existing.expires_at = expires
        return Claim(fresh=True, resource_id=None)
    if existing.request_hash != req_hash or existing.resource_type != resource_type:
        raise AppError(
            "idempotency_key_reuse",
            "this Idempotency-Key was already used for a different request",
            422,
        )
    if existing.resource_id is None:
        # Only reachable if the earlier request died before finishing; it rolled back its row,
        # so this one can safely own the key.
        return Claim(fresh=True, resource_id=None)
    return Claim(fresh=False, resource_id=existing.resource_id)


async def attach(session: AsyncSession, scope: str, resource_id: uuid.UUID) -> None:
    await session.execute(
        sa.update(IdempotencyKey)
        .where(IdempotencyKey.scope_hash == scope)
        .values(resource_id=resource_id)
    )


async def purge_expired(session: AsyncSession, limit: int = 5000) -> int:
    ids = sa.select(IdempotencyKey.id).where(IdempotencyKey.expires_at < datetime.now(UTC)).limit(limit)
    result = await session.execute(sa.delete(IdempotencyKey).where(IdempotencyKey.id.in_(ids)))
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
