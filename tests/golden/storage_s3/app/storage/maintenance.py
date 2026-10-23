"""Housekeeping for the file module (generated). Run it from cron or a scheduler, e.g. hourly:

    python -m app.storage.maintenance                 # clean up, finish deletions, log the digest
    python -m app.storage.maintenance --rescan        # also rescan files not scanned recently
    python -m app.storage.maintenance --purge-audit --yes   # drop audit rows past their retention

It is safe to run at any time and from several places at once: each step claims rows with
FOR UPDATE SKIP LOCKED and does nothing twice.

  purge-pending   a crash between "row written" and "file stored" leaves a `pending` row (and maybe
                  an object): both are removed.
  finish-deletes  a delete whose bucket call failed left the row in `deleting`: it is retried.
  digest          logs a SHA-256 over yesterday's audit hashes. Copy that line to storage you control
                  (a log service, a ticket): it is what proves later that the trail was not rewritten.
  rescan          signatures improve; a file that was clean last month may not be today. Rescans files
                  scanned more than RESCAN_AFTER_DAYS ago; anything not clean is quarantined.
"""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
import structlog

from app.core.logging import configure_logging
from app.db import engine, session_factory
from app.storage import audit, config, service
from app.storage.backend import BackendUnavailable, get_backend
from app.storage.models import StorAuditLog, StorFile

logger = structlog.get_logger()
BATCH = 100
PENDING_GRACE_MINUTES = 60
DELETING_GRACE_MINUTES = 10


def _now() -> datetime:
    return datetime.now(UTC)


async def purge_pending() -> int:
    cutoff = _now() - timedelta(minutes=PENDING_GRACE_MINUTES)
    done = 0
    async with session_factory() as session:
        rows = (
            await session.execute(
                sa.select(StorFile)
                .where(StorFile.status == "pending", StorFile.updated_at < cutoff)
                .order_by(StorFile.updated_at)
                .limit(BATCH)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        for row in rows:
            try:
                await get_backend().delete(row.storage_key)
            except BackendUnavailable:
                logger.warning("storage_pending_purge_deferred", file_id=str(row.id))
                continue
            await audit.append(
                session, event="maintenance.pending_purged", file_id=row.id,
                tenant_id=row.tenant_id, data={"sha256": row.sha256, "size": row.size_bytes},
            )
            await session.delete(row)
            done += 1
        await session.commit()
    return done


async def finish_deletes() -> int:
    cutoff = _now() - timedelta(minutes=DELETING_GRACE_MINUTES)
    done = 0
    async with session_factory() as session:
        rows = (
            await session.execute(
                sa.select(StorFile)
                .where(StorFile.status == "deleting", StorFile.updated_at < cutoff)
                .order_by(StorFile.updated_at)
                .limit(BATCH)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        for row in rows:
            try:
                await service._erase(session, row, actor=None, info=service.RequestInfo())
            except Exception as exc:  # one stuck file must not stop the others
                logger.warning("storage_delete_retry_failed", file_id=str(row.id), error=type(exc).__name__)
                continue
            done += 1
    return done


async def rescan_old(limit: int) -> dict[str, int]:
    cutoff = _now() - timedelta(days=config.RESCAN_AFTER_DAYS)
    counts: dict[str, int] = {}
    async with session_factory() as session:
        rows = (
            await session.execute(
                sa.select(StorFile)
                .where(StorFile.status == "clean", StorFile.scanned_at < cutoff)
                .order_by(StorFile.scanned_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        for row in rows:
            verdict = await service.rescan(session, row, actor_id=None, info=service.RequestInfo())
            counts[verdict] = counts.get(verdict, 0) + 1
            if verdict not in ("clean", "unavailable"):
                logger.error("storage_rescan_quarantined", file_id=str(row.id), verdict=verdict)
    return counts


async def log_digest(day: datetime) -> str:
    async with session_factory() as session:
        digest = await audit.day_digest(session, day)
    logger.info("storage_audit_digest", day=day.date().isoformat(), sha256=digest)
    return digest


async def purge_audit() -> int:
    """Delete audit rows past their retention (the database refuses anything younger)."""
    cutoff = _now() - timedelta(days=config.AUDIT_RETENTION_DAYS)
    async with session_factory() as session:
        await session.execute(sa.text("SET LOCAL storage.allow_audit_purge = 'on'"))
        result = await session.execute(sa.delete(StorAuditLog).where(StorAuditLog.at < cutoff))
        await session.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.storage.maintenance")
    parser.add_argument("--rescan", action="store_true", help="rescan files not scanned recently")
    parser.add_argument("--rescan-limit", type=int, default=200, help="most files to rescan per run")
    parser.add_argument("--purge-audit", action="store_true", help="delete audit rows past retention")
    parser.add_argument("--yes", action="store_true", help="confirm --purge-audit")
    args = parser.parse_args(argv)

    configure_logging("INFO")
    config.get_storage_settings().check()
    try:
        logger.info("storage_pending_purged", count=await purge_pending())
        logger.info("storage_deletes_finished", count=await finish_deletes())
        await log_digest(_now() - timedelta(days=1))
        if args.rescan:
            logger.info("storage_rescan", **await rescan_old(args.rescan_limit))
        if args.purge_audit:
            if not args.yes:
                logger.error("storage_purge_audit_needs_yes")
                return 2
            logger.info("storage_audit_purged", count=await purge_audit())
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
