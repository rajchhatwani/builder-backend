"""Read/write files of a draft workspace (E2). Only custom-zone files are writable; nothing is executed.

Every path is checked lexically and component by component (no symlink, no `.git`, stays inside the
worktree). The file content never goes to the audit row or the log."""

import asyncio
import hashlib
import os
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.generator.zones import zone_for
from app.exceptions import AppError
from app.models.agent import AiRun
from app.models.enums import AuditResult
from app.models.workspace import Workspace
from app.schemas.workspace_files import (
    MAX_FILE_BYTES,
    MAX_LIST_ENTRIES,
    WorkspaceFileEntry,
    WorkspaceFileRead,
)
from app.services import audit_service
from app.services.workspace_service import WorkspaceService

_BUSY_STATES = ("running", "applying")


def _bad_path() -> AppError:
    return AppError("bad_path", "the path is not allowed", 400)


def _safe_target(wt: Path, rel: str) -> Path:
    """The absolute path of `rel` inside the worktree, or AppError. No link may appear on the way."""
    if not rel or len(rel) > 500 or "\x00" in rel or "\\" in rel or rel.startswith("/"):
        raise _bad_path()
    parts = rel.split("/")
    if any(p in ("", ".", "..") or p.lower() == ".git" for p in parts):
        raise _bad_path()
    root = wt.resolve()
    cur = root
    for part in parts:
        cur = cur / part
        if cur.is_symlink():
            raise _bad_path()
    if root not in cur.resolve().parents:
        raise _bad_path()
    return cur


def _list_sync(wt: Path) -> list[WorkspaceFileEntry]:
    out: list[WorkspaceFileEntry] = []
    for dirpath, dirs, files in os.walk(wt, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d.lower() != ".git" and not os.path.islink(os.path.join(dirpath, d)))
        for name in sorted(files):
            full = Path(dirpath) / name
            if full.is_symlink() or not full.is_file():
                continue
            rel = full.relative_to(wt).as_posix()
            zone = zone_for(rel)
            try:
                size = full.stat().st_size
            except OSError:
                continue
            out.append(WorkspaceFileEntry(path=rel, zone=zone, size=size, editable=zone == "custom"))
            if len(out) >= MAX_LIST_ENTRIES:
                return sorted(out, key=lambda e: e.path)
    return sorted(out, key=lambda e: e.path)


def _read_sync(wt: Path, rel: str) -> tuple[str, str]:
    target = _safe_target(wt, rel)
    if not target.is_file():
        raise AppError("file_not_found", "file not found", 404)
    with target.open("rb") as fh:
        data = fh.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise AppError("file_too_large", "the file is larger than 256 KB", 413)
    try:
        if b"\x00" in data:
            raise ValueError
        text = data.decode("utf-8")
    except ValueError:
        raise AppError("file_not_text", "only utf-8 text files can be opened", 415) from None
    return text, hashlib.sha256(data).hexdigest()


def _write_sync(wt: Path, rel: str, content: str, expected: str) -> str:
    target = _safe_target(wt, rel)
    _, current = _read_sync(wt, rel)
    if current != expected:
        raise AppError("file_changed", "the file changed since it was opened", 409)
    if "\x00" in content:
        raise AppError("file_not_text", "the content contains a NUL byte", 415)
    data = content.encode("utf-8")
    if len(data) > MAX_FILE_BYTES:
        raise AppError("file_too_large", "the content is larger than 256 KB", 413)
    mode = target.stat().st_mode & 0o777
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".wsedit-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return hashlib.sha256(data).hexdigest()


class WorkspaceFileService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._ws = WorkspaceService(session)

    async def _worktree(self, project_id: uuid.UUID, ws_id: uuid.UUID, lock: bool = False) -> Path:
        ws: Workspace = await self._ws._get(project_id, ws_id, lock=lock)
        if ws.state != "active" or not ws.worktree_path or not Path(ws.worktree_path).is_dir():
            raise AppError("workspace_inactive", "the workspace is not active", 409)
        return Path(ws.worktree_path)

    async def list_files(self, project_id: uuid.UUID, ws_id: uuid.UUID) -> list[WorkspaceFileEntry]:
        wt = await self._worktree(project_id, ws_id)
        return await asyncio.to_thread(_list_sync, wt)

    async def read(self, project_id: uuid.UUID, ws_id: uuid.UUID, path: str) -> WorkspaceFileRead:
        wt = await self._worktree(project_id, ws_id)
        text, sha = await asyncio.to_thread(_read_sync, wt, path)
        zone = zone_for(path)
        return WorkspaceFileRead(path=path, zone=zone, content=text, editable=zone == "custom", sha256=sha)

    async def write(
        self,
        project_id: uuid.UUID,
        ws_id: uuid.UUID,
        path: str,
        content: str,
        expected_sha256: str,
        *,
        actor_id: uuid.UUID,
        actor_email: str | None,
        via: str,
        organization_id: uuid.UUID | None,
        client_ip: str | None,
        request_id: str | None,
    ) -> WorkspaceFileRead:
        wt = await self._worktree(project_id, ws_id, lock=True)  # row lock held until commit
        zone = zone_for(path)
        if zone != "custom":
            raise AppError("file_not_editable", "only custom-zone files can be edited", 403)
        busy = (
            await self.session.execute(
                select(AiRun.id)
                .where(AiRun.workspace_id == ws_id, AiRun.state.in_(_BUSY_STATES))
                .limit(1)
            )
        ).first()
        if busy is not None:
            raise AppError("workspace_busy", "an agent run is using this workspace", 409)
        sha = await asyncio.to_thread(_write_sync, wt, path, content, expected_sha256)
        await audit_service.record(
            self.session,
            action="workspace.file.write",
            result=AuditResult.ok,
            actor_id=actor_id,
            actor_email=actor_email,
            via=via,
            target_type="workspace",
            target_id=ws_id,
            project_id=project_id,
            organization_id=organization_id,
            client_ip=client_ip,
            request_id=request_id,
            detail={"path": path, "zone": zone, "bytes": len(content.encode("utf-8")), "sha256": sha},
        )
        await self.session.commit()
        return WorkspaceFileRead(path=path, zone=zone, content=content, editable=True, sha256=sha)
