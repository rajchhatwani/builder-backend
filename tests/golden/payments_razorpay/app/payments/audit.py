"""Append-only, hash-chained audit trail (generated).

Every money-relevant change writes one row in the same transaction as the change itself, so the
trail and the data cannot disagree. Rows are chained per payment (and one chain for system
events): each hash covers the previous row's hash, so removing or editing a row is detectable by
`verify_chain`. The chain is per payment, not global, so unrelated payments never queue behind one
another. What it cannot do: stop someone with full database superuser rights from rewriting the
whole chain; ship the daily digest (see jobs) to storage you control to cover that case.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redact import scrub
from app.payments.models import AuditLog

GENESIS = "0" * 64
SYSTEM_CHAIN = "system"
ACTOR_USER = "user"
ACTOR_SYSTEM = "system"
ACTOR_PROVIDER = "provider"


def chain_key_for(payment_id: uuid.UUID | None) -> str:
    return str(payment_id) if payment_id is not None else SYSTEM_CHAIN


def _digest(prev_hash: str, row: dict[str, Any]) -> str:
    canonical = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(f"{prev_hash}|{canonical}".encode("ascii")).hexdigest()


def _row_fields(entry: AuditLog) -> dict[str, Any]:
    return {
        "chain": entry.chain_key,
        "seq": entry.seq,
        "at": entry.at.astimezone(UTC).isoformat(),
        "actor_type": entry.actor_type,
        "actor_id": str(entry.actor_id) if entry.actor_id else None,
        "tenant_id": str(entry.tenant_id) if entry.tenant_id else None,
        "event": entry.event,
        "data": entry.data,
    }


async def append(
    session: AsyncSession,
    *,
    payment_id: uuid.UUID | None,
    event: str,
    data: dict[str, Any] | None = None,
    actor_type: str = ACTOR_SYSTEM,
    actor_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
) -> AuditLog:
    """Add one entry to the chain. The caller commits (the entry belongs to its transaction)."""
    chain = chain_key_for(payment_id)
    # One writer per chain at a time; released when the transaction ends.
    await session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"pay_audit:{chain}"},
    )
    last = (
        await session.execute(
            sa.select(AuditLog.seq, AuditLog.hash)
            .where(AuditLog.chain_key == chain)
            .order_by(AuditLog.seq.desc())
            .limit(1)
        )
    ).first()
    seq, prev = (last[0] + 1, last[1]) if last is not None else (1, GENESIS)
    entry = AuditLog(
        id=uuid.uuid4(),
        chain_key=chain,
        seq=seq,
        at=datetime.now(UTC),
        actor_type=actor_type,
        actor_id=actor_id,
        tenant_id=tenant_id,
        event=event,
        data=scrub(data or {}),
        prev_hash=prev,
        hash="",
    )
    entry.hash = _digest(prev, _row_fields(entry))
    session.add(entry)
    await session.flush()
    return entry


async def verify_chain(
    session: AsyncSession, payment_id: uuid.UUID | None
) -> tuple[bool, int | None]:
    """(True, None) when the chain is intact, else (False, first sequence number that is not)."""
    chain = chain_key_for(payment_id)
    rows = (
        await session.execute(
            sa.select(AuditLog).where(AuditLog.chain_key == chain).order_by(AuditLog.seq)
        )
    ).scalars()
    prev = GENESIS
    expected = 1
    for entry in rows:
        if entry.seq != expected or entry.prev_hash != prev:
            return False, expected
        if _digest(prev, _row_fields(entry)) != entry.hash:
            return False, entry.seq
        prev = entry.hash
        expected += 1
    return True, None


async def day_digest(session: AsyncSession, day: datetime) -> str:
    """SHA-256 over the hashes of one UTC day's entries, in a fixed order. Logged by a job so
    it can be stored outside the database."""
    start = day.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    hashes = (
        await session.execute(
            sa.select(AuditLog.hash)
            .where(AuditLog.at >= start, AuditLog.at < end)
            .order_by(AuditLog.chain_key, AuditLog.seq)
        )
    ).scalars()
    return hashlib.sha256("|".join(hashes).encode("ascii")).hexdigest()

