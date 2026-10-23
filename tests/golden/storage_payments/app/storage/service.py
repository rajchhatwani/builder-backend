"""Upload, download, delete and review of files (generated).

Every refusal writes an audit row first and only then raises, so a denied or rejected request is on
record even though it changes nothing else. Order of an upload, and why:

1. role, rate limit            cheap checks first
2. size and hash               what exactly are we holding (also catches a lying Content-Length)
3. type and allowlist          what it really is, from its bytes
4. quota
5. malware scan                BEFORE anything is stored: an infected file never reaches the bucket,
                               and a scanner that is down means "not stored", never "assume clean"
6. pending row, then the bucket, then the row becomes `clean`
                               a crash in between leaves a `pending` row the maintenance command
                               removes (together with any orphaned object)
"""

import asyncio
import hashlib
import tempfile
import uuid
from collections.abc import AsyncIterator, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, BinaryIO

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthUser
from app.core.errors import AppError, NotFoundError
from app.core.pagination import PageParams
from app.db import session_factory
from app.storage import access, audit, clamav, config, names, refs, sniff
from app.storage.backend import BackendUnavailable, ObjectMissing, get_backend
from app.storage.models import StorAuditLog, StorFile

logger = structlog.get_logger()
READ_CHUNK = 1024 * 1024
SPOOL_MEMORY = 1024 * 1024


@dataclass(frozen=True)
class RequestInfo:
    """Where a request came from, for the audit trail."""

    ip: str | None = None
    request_id: str | None = None


# --- helpers ----------------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _measure(file: BinaryIO, limit: int) -> tuple[int, str]:
    """Size and SHA-256 of the whole file, stopping as soon as the limit is passed."""
    file.seek(0)
    digest = hashlib.sha256()
    size = 0
    while chunk := file.read(READ_CHUNK):
        size += len(chunk)
        if size > limit:
            return size, ""
        digest.update(chunk)
    return size, digest.hexdigest()


def _scanner() -> tuple[str, int, float]:
    settings = config.get_storage_settings()
    return settings.clamd_host, settings.clamd_port, float(settings.storage_scan_timeout_seconds)


async def _refuse(
    session: AsyncSession,
    user: AuthUser,
    info: RequestInfo,
    *,
    event: str,
    code: str,
    message: str,
    status: int,
    outcome: str = audit.REJECTED,
    file_id: uuid.UUID | None = None,
    data: dict[str, object] | None = None,
) -> AppError:
    """Record the refusal, then hand back the error to raise. Nothing is rolled back here: a
    rollback would expire the signed-in user object the caller still holds."""
    await audit.append(
        session,
        event=event,
        outcome=outcome,
        file_id=file_id,
        actor_id=user.id,
        tenant_id=access.tenant_of(user),
        ip=info.ip,
        request_id=info.request_id,
        data={"reason": code, **(data or {})},
    )
    await session.commit()
    return AppError(code, message, status)


async def get_visible(session: AsyncSession, user: AuthUser, file_id: uuid.UUID) -> StorFile:
    """A file the user may see. Anything else is reported as not found."""
    row = (
        await session.execute(
            sa.select(StorFile).where(StorFile.id == file_id, *access.visible_to(user))
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("file not found")
    return row


async def get_for_operator(session: AsyncSession, user: AuthUser, file_id: uuid.UUID) -> StorFile:
    """Any file of the tenant, whatever its state (for the operate role)."""
    access.require_role(user, "operate")
    row = (
        await session.execute(
            sa.select(StorFile).where(StorFile.id == file_id, *access.in_tenant(user))
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("file not found")
    return row


# --- upload -----------------------------------------------------------------------------------


async def upload(
    session: AsyncSession,
    user: AuthUser,
    file: BinaryIO,
    *,
    filename: str | None,
    declared_type: str | None,
    shared: bool,
    info: RequestInfo,
) -> StorFile:
    if not access.has_role(user, "upload") or (shared and not access.has_role(user, "share")):
        raise await _refuse(
            session, user, info, event="upload.denied", code="forbidden",
            message="you do not have permission to do that", status=403, outcome=audit.DENIED,
        )

    # 1. rate limit: attempts of this user in the last hour (accepted or rejected)
    attempts = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(StorAuditLog)
            .where(
                StorAuditLog.chain_key == audit.chain_for(None, user.id),
                StorAuditLog.event.in_(("upload.accepted", "upload.rejected")),
                StorAuditLog.at > _now() - timedelta(hours=1),
            )
        )
    ).scalar_one()
    if attempts >= config.UPLOADS_PER_HOUR:
        raise await _refuse(
            session, user, info, event="upload.rate_limited", code="rate_limited",
            message="too many uploads; try again later", status=429,
        )

    # 2. size and hash
    size, digest = await asyncio.to_thread(_measure, file, config.MAX_FILE_BYTES)
    if size > config.MAX_FILE_BYTES:
        raise await _refuse(
            session, user, info, event="upload.rejected", code="file_too_large",
            message=f"the file is larger than the {config.MAX_FILE_BYTES // (1024 * 1024)} MB limit",
            status=413,
        )
    if size == 0:
        raise await _refuse(
            session, user, info, event="upload.rejected", code="empty_file",
            message="the file is empty", status=422,
        )
    common = {"sha256": digest, "size": size}

    # 3. what it really is
    file.seek(0)
    detected = sniff.detect(await asyncio.to_thread(file.read, sniff.HEAD_BYTES))
    declared = sniff.normalize_declared(declared_type)
    if not sniff.type_allowed(config.ALLOWED_TYPES, detected, declared):
        raise await _refuse(
            session, user, info, event="upload.rejected", code="type_not_allowed",
            message="this type of file is not accepted", status=415,
            data={**common, "detected_type": detected.mime, "declared_type": declared},
        )

    # 4. quota
    if config.USER_QUOTA_BYTES is not None:
        used = (
            await session.execute(
                sa.select(sa.func.coalesce(sa.func.sum(StorFile.size_bytes), 0)).where(
                    StorFile.created_by_id == user.id,
                    StorFile.status.in_(("pending", "clean", "quarantined", "deleting")),
                )
            )
        ).scalar_one()
        if used + size > config.USER_QUOTA_BYTES:
            raise await _refuse(
                session, user, info, event="upload.rejected", code="quota_exceeded",
                message="this upload would exceed your storage quota", status=422, data=common,
            )

    # 5. malware scan, before anything is stored
    host, port, timeout = _scanner()
    file.seek(0)
    try:
        verdict = await clamav.scan(file, host=host, port=port, timeout=timeout)
    except clamav.ScannerUnavailable as exc:
        logger.error("storage_scanner_unavailable", reason=str(exc))
        raise await _refuse(
            session, user, info, event="upload.rejected", code="scanner_unavailable",
            message="files cannot be accepted right now because the malware scan is unavailable",
            status=503, outcome=audit.ERROR, data=common,
        ) from exc
    if not verdict.clean:
        raise await _refuse(
            session, user, info, event="upload.rejected", code="malware_detected",
            message="the file was rejected by the malware scan", status=422,
            data={**common, "detection": verdict.signature, "detected_type": detected.mime},
        )
    engine = await clamav.engine_version(host, port)

    # 6. pending row, bucket, clean row
    file_id = uuid.uuid4()
    now = _now()
    row = StorFile(
        id=file_id,
        tenant_id=access.tenant_of(user),
        created_by_id=user.id,
        status="pending",
        shared=shared,
        original_name=names.safe_filename(filename),
        declared_type=declared,
        detected_type=detected.mime,
        size_bytes=size,
        sha256=digest,
        storage_key=names.make_key(config.KEY_PREFIX, access.tenant_of(user), file_id, now),
    )
    session.add(row)
    await session.commit()
    try:
        file.seek(0)
        await get_backend().put(row.storage_key, file, sha256=digest)
    except BackendUnavailable as exc:
        await session.delete(row)
        await session.commit()
        raise await _refuse(
            session, user, info, event="upload.rejected", code="storage_unavailable",
            message="the file could not be stored right now", status=503, outcome=audit.ERROR,
            data=common,
        ) from exc
    row.status = "clean"
    row.scanned_at = _now()
    row.scan_engine = engine
    await audit.append(
        session,
        event="upload.accepted",
        file_id=row.id,
        actor_id=user.id,
        tenant_id=row.tenant_id,
        ip=info.ip,
        request_id=info.request_id,
        data={
            **common,
            "detected_type": detected.mime,
            "declared_type": declared,
            "declared_matches": declared == detected.mime,
            "shared": shared,
            "scan_engine": engine,
        },
    )
    # The accepted upload also counts against the rate limit, which reads the user's own chain.
    await audit.append(
        session,
        event="upload.accepted",
        actor_id=user.id,
        tenant_id=row.tenant_id,
        ip=info.ip,
        request_id=info.request_id,
        data={"file_id": str(row.id), "size": size},
    )
    await session.commit()
    return row


# --- list, read, download ---------------------------------------------------------------------


async def list_files(
    session: AsyncSession, user: AuthUser, page: PageParams, *, mine: bool = False
) -> tuple[list[StorFile], int]:
    conditions = access.visible_to(user)
    if mine:
        conditions.append(StorFile.created_by_id == user.id)
    total = (
        await session.execute(sa.select(sa.func.count()).select_from(StorFile).where(*conditions))
    ).scalar_one()
    rows = (
        await session.execute(
            sa.select(StorFile)
            .where(*conditions)
            .order_by(StorFile.created_at.desc(), StorFile.id)
            .limit(page.limit)
            .offset(page.offset)
        )
    ).scalars()
    return list(rows), total


@dataclass
class Download:
    row: StorFile
    headers: dict[str, str]
    stream: AsyncIterator[bytes] | None = None
    redirect_url: str | None = None


SAFETY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "Cache-Control": "private, no-store",
}


async def prepare_download(
    session: AsyncSession, user: AuthUser, file_id: uuid.UUID, *, inline: bool, info: RequestInfo
) -> Download:
    row = await get_visible(session, user, file_id)
    if row.status != "clean":
        raise await _refuse(
            session, user, info, event="download.denied", code="file_unavailable",
            message="this file is blocked and cannot be downloaded", status=409,
            outcome=audit.DENIED, file_id=row.id, data={"status": row.status},
        )
    show_inline = inline and config.ALLOW_INLINE_IMAGES and row.detected_type in sniff.INLINE_SAFE
    name = row.original_name or "file"
    disposition = names.content_disposition(name, inline=show_inline)
    backend = get_backend()
    mode = config.DOWNLOAD_MODE
    event_data = {"mode": mode, "inline": show_inline, "sha256": row.sha256}

    if mode == "presigned":
        url = backend.presign(
            row.storage_key,
            filename_header=names.content_disposition(name),
            ttl=config.PRESIGN_TTL_SECONDS,
        )
        await _audit_download(session, user, row, info, event_data)
        return Download(row, {"Cache-Control": "no-store"}, redirect_url=url)

    stream = backend.stream(row.storage_key)
    try:
        first = await anext(stream)  # fail with a proper status if the object cannot be read
    except (ObjectMissing, BackendUnavailable, StopAsyncIteration) as exc:
        logger.error("storage_object_unreadable", file_id=str(row.id))
        await audit.append(
            session, event="download.failed", outcome=audit.ERROR, file_id=row.id,
            actor_id=user.id, tenant_id=row.tenant_id, ip=info.ip, request_id=info.request_id,
            data={"reason": type(exc).__name__},
        )
        await session.commit()
        raise AppError("storage_unavailable", "the file cannot be read right now", 503) from exc
    await _audit_download(session, user, row, info, event_data)
    headers = {
        "Content-Type": sniff.served_type(row.detected_type),
        "Content-Disposition": disposition,
        "Content-Length": str(row.size_bytes),
        **SAFETY_HEADERS,
    }
    return Download(row, headers, stream=_verified(first, stream, row))


async def _audit_download(
    session: AsyncSession, user: AuthUser, row: StorFile, info: RequestInfo, data: dict[str, object]
) -> None:
    await audit.append(
        session,
        event="download.granted",
        file_id=row.id,
        actor_id=user.id,
        tenant_id=row.tenant_id,
        ip=info.ip,
        request_id=info.request_id,
        data=data,
    )
    await session.commit()


async def _verified(
    first: bytes, rest: AsyncIterator[bytes], row: StorFile
) -> AsyncIterator[bytes]:
    """Streams the object while hashing it. When the stream ends, a size or hash that differs from
    what was recorded at upload is reported (the headers are already sent by then, so the client
    sees the bytes; what changes is that the file is quarantined and the event audited)."""
    digest = hashlib.sha256(first)
    total = len(first)
    file_id, expected_hash, expected_size = row.id, row.sha256, row.size_bytes
    yield first
    async for chunk in rest:
        digest.update(chunk)
        total += len(chunk)
        yield chunk
    if total == expected_size and digest.hexdigest() == expected_hash:
        return
    logger.error("storage_integrity_mismatch", file_id=str(file_id))
    # The server cancels a request's task as soon as its response is complete, which would cancel
    # a database write started here. A detached task is not affected.
    _detach(_record_mismatch(file_id, expected_hash, digest.hexdigest(), total))


_background: set["asyncio.Task[None]"] = set()


def _detach(work: Coroutine[Any, Any, None]) -> None:
    task = asyncio.get_running_loop().create_task(work)
    _background.add(task)  # keep a reference, or the task may be collected before it finishes
    task.add_done_callback(_background.discard)


async def wait_for_background() -> None:
    """Wait for detached work (tests use this; the server never needs to)."""
    await asyncio.gather(*list(_background), return_exceptions=True)


async def _record_mismatch(file_id: uuid.UUID, expected: str, got: str, size: int) -> None:
    try:
        async with session_factory() as session:
            row = (
                await session.execute(
                    sa.select(StorFile).where(StorFile.id == file_id).with_for_update()
                )
            ).scalar_one_or_none()
            if row is not None and row.status == "clean":
                row.status = "quarantined"
                row.quarantine_reason = "integrity"
            await audit.append(
                session,
                event="download.integrity_mismatch",
                outcome=audit.ERROR,
                file_id=file_id,
                tenant_id=row.tenant_id if row is not None else None,
                data={"expected": expected, "got": got, "size": size},
            )
            await session.commit()
    except Exception:  # nothing may escape a detached task
        logger.exception("storage_integrity_audit_failed", file_id=str(file_id))


# --- delete -----------------------------------------------------------------------------------


async def delete_file(
    session: AsyncSession, user: AuthUser, file_id: uuid.UUID, info: RequestInfo
) -> None:
    row = await get_visible(session, user, file_id)
    allowed = access.has_role(user, "delete_all") or (
        access.has_role(user, "delete") and row.created_by_id == user.id
    )
    if not allowed:
        raise await _refuse(
            session, user, info, event="delete.denied", code="forbidden",
            message="you do not have permission to do that", status=403,
            outcome=audit.DENIED, file_id=row.id,
        )
    await _erase(session, row, actor=user, info=info)


async def _erase(
    session: AsyncSession, row: StorFile, *, actor: AuthUser | None, info: RequestInfo
) -> None:
    """Remove the bytes, then blank the name and keep a tombstone (id, hash, size, dates)."""
    locked = (
        await session.execute(sa.select(StorFile).where(StorFile.id == row.id).with_for_update())
    ).scalar_one()
    if locked.status not in ("clean", "quarantined", "pending", "deleting"):
        return
    previous = locked.status
    locked.status = "deleting"
    await session.commit()  # new references are refused from here on (they need status clean)
    if await refs.is_referenced(session, locked.id):
        locked.status = previous
        await session.commit()
        if actor is not None:
            raise await _refuse(
                session, actor, info, event="delete.rejected", code="file_in_use",
                message="the file is still used by a record: remove it from there first",
                status=409, file_id=locked.id,
            )
        return
    try:
        await get_backend().delete(locked.storage_key)
    except BackendUnavailable as exc:
        await audit.append(
            session, event="delete.failed", outcome=audit.ERROR, file_id=locked.id,
            actor_id=actor.id if actor else None, tenant_id=locked.tenant_id, ip=info.ip,
            request_id=info.request_id, data={},
        )
        await session.commit()
        raise AppError(
            "storage_unavailable", "the file could not be deleted right now; it will be retried", 503
        ) from exc
    locked.status = "deleted"
    locked.original_name = None
    locked.deleted_at = _now()
    await audit.append(
        session, event="file.deleted", file_id=locked.id, actor_id=actor.id if actor else None,
        tenant_id=locked.tenant_id, ip=info.ip, request_id=info.request_id,
        data={"sha256": locked.sha256, "size": locked.size_bytes, "previous_status": previous},
    )
    await session.commit()


# --- review (operate role) ---------------------------------------------------------------------


async def quarantine(
    session: AsyncSession, user: AuthUser, file_id: uuid.UUID, reason: str, info: RequestInfo
) -> StorFile:
    row = await get_for_operator(session, user, file_id)
    if row.status != "clean":
        raise AppError("invalid_state", "only an available file can be quarantined", 409)
    row.status = "quarantined"
    row.quarantine_reason = reason[:64] if reason else "manual"
    await audit.append(
        session, event="file.quarantined", file_id=row.id, actor_id=user.id,
        tenant_id=row.tenant_id, ip=info.ip, request_id=info.request_id,
        data={"reason": row.quarantine_reason},
    )
    await session.commit()
    return row


async def release(
    session: AsyncSession, user: AuthUser, file_id: uuid.UUID, info: RequestInfo
) -> StorFile:
    """Lifts a quarantine only if the stored bytes still match their hash and scan clean now."""
    row = await get_for_operator(session, user, file_id)
    if row.status != "quarantined":
        raise AppError("invalid_state", "the file is not quarantined", 409)
    verdict = await rescan(session, row, actor_id=user.id, info=info)
    if verdict != "clean":
        raise AppError(
            "release_refused", "the file did not pass the checks and stays quarantined", 409
        )
    row.status = "clean"
    row.quarantine_reason = None
    await audit.append(
        session, event="file.released", file_id=row.id, actor_id=user.id,
        tenant_id=row.tenant_id, ip=info.ip, request_id=info.request_id, data={},
    )
    await session.commit()
    return row


async def rescan(
    session: AsyncSession, row: StorFile, *, actor_id: uuid.UUID | None, info: RequestInfo
) -> str:
    """Fetch the stored bytes, compare their hash, scan them again. Returns `clean`, `infected`,
    `tampered` (hash differs from the one recorded at upload), `missing` or `unavailable`. A file
    that is not clean is quarantined; the verdict is audited either way."""
    host, port, timeout = _scanner()
    with tempfile.SpooledTemporaryFile(max_size=SPOOL_MEMORY) as spool:
        digest = hashlib.sha256()
        try:
            async for chunk in get_backend().stream(row.storage_key):
                digest.update(chunk)
                await asyncio.to_thread(spool.write, chunk)
        except ObjectMissing:
            return await _rescan_result(session, row, "missing", actor_id, info, {})
        except BackendUnavailable:
            return "unavailable"
        if digest.hexdigest() != row.sha256:
            return await _rescan_result(session, row, "tampered", actor_id, info, {})
        spool.seek(0)
        try:
            verdict = await clamav.scan(spool, host=host, port=port, timeout=timeout)
        except clamav.ScannerUnavailable:
            return "unavailable"
    if not verdict.clean:
        return await _rescan_result(
            session, row, "infected", actor_id, info, {"detection": verdict.signature}
        )
    row.scanned_at = _now()
    row.scan_engine = await clamav.engine_version(host, port)
    await audit.append(
        session, event="file.rescanned", file_id=row.id, actor_id=actor_id,
        tenant_id=row.tenant_id, ip=info.ip, request_id=info.request_id,
        data={"verdict": "clean", "scan_engine": row.scan_engine},
    )
    await session.commit()
    return "clean"


async def _rescan_result(
    session: AsyncSession,
    row: StorFile,
    verdict: str,
    actor_id: uuid.UUID | None,
    info: RequestInfo,
    data: dict[str, object],
) -> str:
    row.status = "quarantined"
    row.quarantine_reason = verdict
    await audit.append(
        session, event="file.rescanned", outcome=audit.ERROR, file_id=row.id, actor_id=actor_id,
        tenant_id=row.tenant_id, ip=info.ip, request_id=info.request_id,
        data={"verdict": verdict, **data},
    )
    await session.commit()
    return verdict


async def audit_trail(
    session: AsyncSession, user: AuthUser, file_id: uuid.UUID
) -> tuple[bool, int | None, list[StorAuditLog]]:
    row = await get_for_operator(session, user, file_id)
    ok, bad = await audit.verify_chain(session, row.id)
    entries = (
        await session.execute(
            sa.select(StorAuditLog)
            .where(StorAuditLog.chain_key == str(row.id))
            .order_by(StorAuditLog.seq)
        )
    ).scalars()
    return ok, bad, list(entries)
