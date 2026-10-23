"""Append-only, hash-chained audit trail of file activity (generated).

One row per security-relevant event, written in the same transaction as the change it describes, so
the trail and the data cannot disagree. A row says who (user id, optional IP address), what (event,
file id, hash, size, type), when and with what outcome. It never holds file contents or a file
name: names can identify a person, and the trail is kept for years.

Rows are chained per file (and per user for uploads that never became a file): each hash covers the
previous row's hash, so removing or editing a row is detectable by `verify_chain`. What a chain
cannot do is stop someone with full database superuser rights from rewriting everything; ship the
digest (see maintenance) to storage you control to cover that case.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redact import scrub
from app.storage.models import StorAuditLog

GENESIS = "0" * 64
SYSTEM_CHAIN = "system"

OK = "ok"
DENIED = "denied"
REJECTED = "rejected"
ERROR = "error"


def chain_for(file_id: uuid.UUID | None, actor_id: uuid.UUID | None) -> str:
    if file_id is not None:
        return str(file_id)
    return f"actor:{actor_id}" if actor_id is not None else SYSTEM_CHAIN


def _digest(prev_hash: str, row: dict[str, Any]) -> str:
    canonical = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(f"{prev_hash}|{canonical}".encode("ascii")).hexdigest()


def _row_fields(entry: StorAuditLog) -> dict[str, Any]:
    return {
        "chain": entry.chain_key,
        "seq": entry.seq,
        "at": entry.at.astimezone(UTC).isoformat(),
        "actor_id": str(entry.actor_id) if entry.actor_id else None,
        "tenant_id": str(entry.tenant_id) if entry.tenant_id else None,
        "file_id": str(entry.file_id) if entry.file_id else None,
        "event": entry.event,
        "outcome": entry.outcome,
        "ip": entry.ip,
        "request_id": entry.request_id,
        "data": entry.data,
    }


async def append(
    session: AsyncSession,
    *,
    event: str,
    outcome: str = OK,
    file_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    ip: str | None = None,
    request_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> StorAuditLog:
    """Add one entry to the chain. The caller commits (the entry belongs to its transaction)."""
    chain = chain_for(file_id, actor_id)
    # One writer per chain at a time; released when the transaction ends.
    await session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"stor_audit:{chain}"},
    )
    last = (
        await session.execute(
            sa.select(StorAuditLog.seq, StorAuditLog.hash)
            .where(StorAuditLog.chain_key == chain)
            .order_by(StorAuditLog.seq.desc())
            .limit(1)
        )
    ).first()
    seq, prev = (last[0] + 1, last[1]) if last is not None else (1, GENESIS)
    entry = StorAuditLog(
        id=uuid.uuid4(),
        chain_key=chain,
        seq=seq,
        at=datetime.now(UTC),
        actor_id=actor_id,
        tenant_id=tenant_id,
        file_id=file_id,
        event=event,
        outcome=outcome,
        ip=ip,
        request_id=request_id,
        data=scrub(data or {}),
        prev_hash=prev,
        hash="",
    )
    entry.hash = _digest(prev, _row_fields(entry))
    session.add(entry)
    await session.flush()
    return entry


async def verify_chain(
    session: AsyncSession, file_id: uuid.UUID | None, actor_id: uuid.UUID | None = None
) -> tuple[bool, int | None]:
    """(True, None) when the chain is intact, else (False, first sequence number that is not)."""
    chain = chain_for(file_id, actor_id)
    rows = (
        await session.execute(
            sa.select(StorAuditLog).where(StorAuditLog.chain_key == chain).order_by(StorAuditLog.seq)
        )
    ).scalars()
    prev: str | None = None
    expected: int | None = None
    for entry in rows:
        if prev is None or expected is None:
            # The chain starts here. After a purge of old rows it no longer starts at 1: the
            # first surviving row is then the anchor (its own hash is still checked below).
            if entry.seq == 1 and entry.prev_hash != GENESIS:
                return False, 1
            prev, expected = entry.prev_hash, entry.seq
        if entry.seq != expected or entry.prev_hash != prev:
            return False, expected
        if _digest(prev, _row_fields(entry)) != entry.hash:
            return False, entry.seq
        prev = entry.hash
        expected += 1
    return True, None


async def day_digest(session: AsyncSession, day: datetime) -> str:
    """SHA-256 over the hashes of one UTC day's entries, in a fixed order. Logged by the
    maintenance command so it can be stored outside the database."""
    start = day.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    hashes = (
        await session.execute(
            sa.select(StorAuditLog.hash)
            .where(StorAuditLog.at >= start, StorAuditLog.at < end)
            .order_by(StorAuditLog.chain_key, StorAuditLog.seq)
        )
    ).scalars()
    return hashlib.sha256("|".join(hashes).encode("ascii")).hexdigest()
