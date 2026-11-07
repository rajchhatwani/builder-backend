"""Draft workspaces (B3-4, architecture 6.4): spec ref + git worktree + preview DB + checkpoints.

A workspace never touches the project's real spec or any production system. Checkpoint =
(git commit + tag, spec op-log sequence + hash, snapshot database cloned from the preview DB).
Rollback restores all three. Every external name (branch, database, path) is derived from a
UUID hex we generated, never from user text; git runs with hooks and global config disabled.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import Settings, get_settings
from app.core.generator import InvalidSpecError, generate
from app.core.spec_models import Spec, spec_hash
from app.exceptions import AppError
from app.models.project import Project
from app.models.spec_op import SpecOp
from app.models.workspace import Workspace, WorkspaceCheckpoint
from app.schemas.workspace import CheckpointRead, WorkspaceRead
from app.services.spec_service import SpecService

log = logging.getLogger(__name__)
ACTIVE_STATES = ("active", "rolled_back")
BUSY_STATES = ("creating", "checkpointing", "rolling_back")
COUNTED_STATES = (*ACTIVE_STATES, *BUSY_STATES)
BUSY_STALE = timedelta(minutes=10)  # a crashed worker's busy marker can be re-claimed after this
_DB_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
# git control files (.gitignore / .github are ordinary files and stay allowed)
_UNSAFE_NAME = re.compile(r"^\.git(attributes|modules|config)?$", re.IGNORECASE)
_GIT_IDENT = ["-c", "user.name=builder", "-c", "user.email=builder@localhost"]


def _unavailable() -> AppError:
    return AppError("workspaces_unavailable", "draft workspaces are not configured", 503)


def _not_found() -> AppError:
    return AppError("not_found", "workspace not found", 404)


def checkpoint_read(c: WorkspaceCheckpoint) -> CheckpointRead:
    return CheckpointRead(
        id=c.id,
        workspace_id=c.workspace_id,
        label=c.label,
        git_sha=c.git_sha,
        spec_seq=c.spec_seq,
        spec_hash=c.spec_hash,
        has_data_snapshot=c.db_snapshot is not None,
        created_at=c.created_at,
    )


def workspace_read(w: Workspace, cps: list[WorkspaceCheckpoint]) -> WorkspaceRead:
    return WorkspaceRead(
        id=w.id,
        project_id=w.project_id,
        name=w.name,
        state=w.state,
        base_spec_seq=w.base_spec_seq,
        spec_seq=w.spec_seq,
        branch=w.branch,
        created_at=w.created_at,
        updated_at=w.updated_at,
        checkpoints=[checkpoint_read(c) for c in cps],
        cleanup_incomplete=w.state == "discarded" and w.preview_db_name is not None,
    )


class WorkspaceService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    # -- plumbing --------------------------------------------------------------------------
    def _root(self) -> Path:
        if not self.settings.workspace_root or self.settings.workspace_db_admin_url is None:
            raise _unavailable()
        template = self.settings.workspace_template_db
        if template and not _DB_IDENT.match(template):
            log.error("workspace_template_db is not a plain identifier")
            raise _unavailable()
        return Path(self.settings.workspace_root).resolve()

    def _repo(self, project_id: uuid.UUID) -> Path:
        return self._root() / str(project_id) / "repo"

    async def _git(self, cwd: Path, *args: str) -> str:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self._root()),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
        }
        proc = await asyncio.create_subprocess_exec(
            "git", "-c", "core.hooksPath=/dev/null", "-c", "protocol.allow=never", *_GIT_IDENT,
            *args,
            cwd=cwd, env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )  # fmt: skip
        try:
            out, err = await asyncio.wait_for(proc.communicate(), 120)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            log.error("git timed out: %s", args[0])
            raise AppError(
                "workspace_git_failed", "workspace git operation timed out", 500
            ) from None
        if proc.returncode != 0:
            # stderr carries host paths: log it, never return it.
            log.error("git %s failed: %s", args[0], err.decode(errors="replace")[:500])
            raise AppError("workspace_git_failed", "workspace git operation failed", 500)
        return out.decode().strip()

    async def _admin(self, *statements: str) -> None:
        """Run DDL on the preview server in autocommit (CREATE/DROP DATABASE)."""
        assert self.settings.workspace_db_admin_url is not None
        engine = create_async_engine(
            self.settings.workspace_db_admin_url.get_secret_value(),
            isolation_level="AUTOCOMMIT",
        )
        try:
            async with engine.connect() as conn:
                for stmt in statements:
                    await conn.execute(text(stmt))
        finally:
            await engine.dispose()

    @staticmethod
    def _kick(db: str) -> str:
        return (
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{db}' AND pid <> pg_backend_pid()"
        )

    def _clone(self, new: str, source: str, kick: bool = True) -> list[str]:
        # A shared template is never kicked: it must be idle (CREATE ... TEMPLATE fails if not).
        pre = [self._kick(source)] if kick else []
        return [*pre, f'CREATE DATABASE "{new}" TEMPLATE "{source}"']

    async def _db_size(self, db: str) -> int:
        assert self.settings.workspace_db_admin_url is not None
        engine = create_async_engine(self.settings.workspace_db_admin_url.get_secret_value())
        try:
            async with engine.connect() as conn:
                row = await conn.execute(text("SELECT pg_database_size(:d)"), {"d": db})
                return int(row.scalar_one())
        finally:
            await engine.dispose()

    @staticmethod
    def _scan(wt: Path) -> tuple[int, list[str]]:
        """(total bytes, unsafe paths): symlinks and .git* names below the worktree root."""
        total, bad = 0, []
        for dirpath, dirnames, filenames in os.walk(wt, followlinks=False):
            at_root = Path(dirpath) == wt
            if at_root:  # our own repo metadata (a worktree's .git is a file)
                dirnames[:] = [d for d in dirnames if d != ".git"]
                filenames = [f for f in filenames if f != ".git"]
            for name in [*dirnames, *filenames]:
                full = Path(dirpath) / name
                if full.is_symlink() or _UNSAFE_NAME.match(name):
                    bad.append(str(full.relative_to(wt)))
            for name in filenames:
                full = Path(dirpath) / name
                if not full.is_symlink():
                    total += full.stat().st_size
        return total, bad

    async def _check_worktree(self, wt: Path) -> None:
        total, bad = await asyncio.to_thread(self._scan, wt)
        if bad:
            raise AppError(
                "workspace_unsafe_files",
                "symlinks and .git* files are not allowed in a workspace",
                422,
                details=[{"path": p} for p in bad[:20]],
            )
        if total > self.settings.workspace_max_disk_bytes:
            raise AppError("workspace_disk_quota", "workspace exceeds its disk quota", 409)

    async def _check_db_size(self, db: str) -> None:
        if await self._db_size(db) > self.settings.workspace_max_db_bytes:
            raise AppError("workspace_db_quota", "preview database exceeds its size quota", 409)

    async def _spec_seq(self, project_id: uuid.UUID) -> int:
        q = select(func.coalesce(func.max(SpecOp.seq), 0)).where(SpecOp.project_id == project_id)
        return int((await self.session.execute(q)).scalar_one())

    # -- reads -----------------------------------------------------------------------------
    async def _get(self, project_id: uuid.UUID, ws_id: uuid.UUID, lock: bool = False) -> Workspace:
        q = select(Workspace).where(Workspace.id == ws_id, Workspace.project_id == project_id)
        row = (await self.session.execute(q.with_for_update() if lock else q)).scalar_one_or_none()
        if row is None:
            raise _not_found()
        return row

    async def _checkpoints(self, ws_id: uuid.UUID) -> list[WorkspaceCheckpoint]:
        q = select(WorkspaceCheckpoint).where(WorkspaceCheckpoint.workspace_id == ws_id)
        return list(
            (await self.session.execute(q.order_by(WorkspaceCheckpoint.created_at))).scalars()
        )

    async def read(self, project_id: uuid.UUID, ws_id: uuid.UUID) -> WorkspaceRead:
        ws = await self._get(project_id, ws_id)
        return workspace_read(ws, await self._checkpoints(ws.id))

    async def list_workspaces(self, project_id: uuid.UUID) -> list[WorkspaceRead]:
        q = select(Workspace).where(Workspace.project_id == project_id)
        rows = (await self.session.execute(q.order_by(Workspace.created_at))).scalars().all()
        return [workspace_read(w, await self._checkpoints(w.id)) for w in rows]

    # -- state claims (short locks; slow work happens with no row lock held) -------------------
    async def _claim(
        self, project_id: uuid.UUID, ws_id: uuid.UUID, busy: str
    ) -> tuple[str, Path, str]:
        """Lock the workspace row briefly, mark it busy and commit. Returns the previous state,
        worktree path and preview DB name. A stale busy marker (crashed worker) can be taken."""
        ws = await self._get(project_id, ws_id, lock=True)
        stale = datetime.now(UTC) - ws.updated_at > BUSY_STALE
        if ws.state in BUSY_STATES and not stale:
            raise AppError("workspace_busy", "another operation is running on this workspace", 409)
        if ws.state not in (*ACTIVE_STATES, *BUSY_STATES):
            raise AppError("workspace_discarded", "workspace is discarded", 409)
        prev = "active" if ws.state in BUSY_STATES else ws.state
        if not ws.worktree_path or not ws.preview_db_name:
            raise AppError("workspace_discarded", "workspace is discarded", 409)
        wt, db = Path(ws.worktree_path), ws.preview_db_name
        ws.state = busy
        await self.session.commit()
        return prev, wt, db

    async def _release(
        self, project_id: uuid.UUID, ws_id: uuid.UUID, state: str, **fields: int
    ) -> None:
        ws = await self._get(project_id, ws_id, lock=True)
        ws.state = state
        for k, v in fields.items():
            setattr(ws, k, v)
        await self.session.commit()

    # -- create ----------------------------------------------------------------------------
    async def create(self, project_id: uuid.UUID, user_id: uuid.UUID, name: str) -> WorkspaceRead:
        root = self._root()
        spec = await SpecService(self.session).assemble(project_id)
        try:
            files = generate(spec)
        except InvalidSpecError as exc:
            raise AppError(
                "spec_invalid", f"spec has {len(exc.issues)} validation issue(s)", 422,
                details=[i.model_dump() for i in exc.issues],
            ) from exc  # fmt: skip
        digest = spec_hash(spec)
        if sum(len(c.encode()) for c in files.values()) > self.settings.workspace_max_disk_bytes:
            raise AppError("workspace_disk_quota", "generated project exceeds the disk quota", 409)

        ws_id = uuid.uuid4()
        hexid = ws_id.hex
        wt = root / str(project_id) / "wt" / hexid
        branch, db = f"ws-{hexid}", f"bbws_{hexid}"
        # Claim: the project row is locked only for this count + insert, then released by commit.
        project = (
            await self.session.execute(
                select(Project).where(Project.id == project_id).with_for_update()
            )
        ).scalar_one_or_none()
        if project is None:
            raise AppError("not_found", "project not found", 404)
        active = (
            await self.session.execute(
                select(func.count())
                .select_from(Workspace)
                .where(Workspace.project_id == project_id, Workspace.state.in_(COUNTED_STATES))
            )
        ).scalar_one()
        if active >= self.settings.workspace_max_active_per_project:
            raise AppError("workspace_limit", "too many active workspaces for this project", 409)
        seq = await self._spec_seq(project_id)
        self.session.add(
            Workspace(
                id=ws_id,
                project_id=project_id,
                name=name,
                state="creating",
                base_spec_seq=seq,
                spec_seq=seq,
                branch=branch,
                worktree_path=str(wt),
                preview_db_name=db,
                created_by=user_id,
            )  # fmt: skip
        )
        await self.session.commit()

        repo = self._repo(project_id)
        try:
            if not (repo / ".git").exists():
                repo.mkdir(parents=True, exist_ok=True)
                await self._git(repo, "init", "-q", "-b", "main")
                await self._git(repo, "commit", "-q", "--allow-empty", "-m", "base")
            wt.parent.mkdir(parents=True, exist_ok=True)
            await self._git(repo, "worktree", "add", "-q", "-b", branch, str(wt), "main")
            for rel, content in files.items():
                self._write_generated(wt, rel, content)
            template = self.settings.workspace_template_db
            if template:
                await self._admin(*self._clone(db, template, kick=False))
            else:
                await self._admin(f'CREATE DATABASE "{db}"')
            ws = await self._get(project_id, ws_id)
            await self._take_checkpoint(ws, "created", spec_digest=digest)
            ws.state = "active"
            await self.session.commit()
        except BaseException:
            await self.session.rollback()
            await self._cleanup(project_id, wt, branch, db, [])
            snaps = list(
                (
                    await self.session.execute(
                        select(WorkspaceCheckpoint.db_snapshot).where(
                            WorkspaceCheckpoint.workspace_id == ws_id
                        )
                    )
                ).scalars()
            )
            await self._cleanup(project_id, wt, branch, db, [x for x in snaps if x])
            gone = await self._get(project_id, ws_id, lock=True)
            await self.session.delete(gone)
            await self.session.commit()
            raise
        return await self.read(project_id, ws_id)

    @staticmethod
    def _write_generated(wt: Path, rel: str, content: str) -> None:
        parts = Path(rel).parts
        if (
            not parts
            or Path(rel).is_absolute()
            or any(p in ("", ".", "..") or _UNSAFE_NAME.match(p) for p in parts)
        ):
            raise AppError("workspace_bad_path", "generated path not allowed", 500)
        cur = wt
        for part in parts[:-1]:
            cur = cur / part
            if cur.is_symlink():
                raise AppError("workspace_bad_path", "generated path not allowed", 500)
        target = wt / rel
        if target.is_symlink() or wt.resolve() not in target.resolve().parents:
            raise AppError("workspace_bad_path", "generated path not allowed", 500)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")

    async def sync_generated(self, project_id: uuid.UUID, ws_id: uuid.UUID, spec: Spec | None = None) -> int:
        """Rewrite the GENERATED-zone files of the draft from the current spec (agent spec edits
        flow into the draft this way). Custom and seeded files are never touched, so an edit to a
        generated file is overwritten, not kept. `spec` is the run's draft spec (H2); default the live one.
        Returns the number of files written."""
        ws = await self._get(project_id, ws_id)
        if ws.state != "active" or not ws.worktree_path:
            raise AppError("workspace_inactive", "the workspace is not active", 409)
        files = generate(spec if spec is not None else await SpecService(self.session).assemble(project_id))
        try:
            zones_doc = json.loads(files.get("platform/zones.json", "{}"))
        except ValueError:
            zones_doc = {}
        zones = zones_doc.get("zones") or {}
        wt, written = Path(ws.worktree_path), 0
        for rel, content in files.items():
            target = wt / rel
            if zones.get(rel, "generated") != "generated":
                if not target.exists() and not target.is_symlink():  # custom/seeded: create, never overwrite
                    self._write_generated(wt, rel, content)
                    written += 1
                continue
            if target.is_file() and not target.is_symlink() and target.read_text("utf-8") == content:
                continue
            self._write_generated(wt, rel, content)
            written += 1
        return written

    # -- checkpoints -----------------------------------------------------------------------
    async def _take_checkpoint(
        self, ws: Workspace, label: str, spec_digest: str | None = None
    ) -> WorkspaceCheckpoint:
        existing = len(await self._checkpoints(ws.id))
        if existing >= self.settings.workspace_max_checkpoints:
            raise AppError("checkpoint_limit", "checkpoint limit reached for this workspace", 409)
        assert ws.worktree_path and ws.preview_db_name
        wt = Path(ws.worktree_path)
        await self._check_worktree(wt)
        await self._check_db_size(ws.preview_db_name)
        if spec_digest is None:
            spec_digest = spec_hash(await SpecService(self.session).assemble(ws.project_id))
        cp_id = uuid.uuid4()
        tag = f"cp-{cp_id.hex}"
        snap = f"bbcp_{cp_id.hex}"
        await self._git(wt, "add", "-A")
        await self._git(wt, "commit", "-q", "--allow-empty", "-m", f"checkpoint: {label}"[:200])
        sha = await self._git(wt, "rev-parse", "HEAD")
        await self._git(wt, "tag", tag, sha)
        await self._admin(*self._clone(snap, ws.preview_db_name))
        cp = WorkspaceCheckpoint(
            id=cp_id, workspace_id=ws.id, project_id=ws.project_id, label=label, git_sha=sha,
            git_tag=tag, spec_seq=ws.spec_seq, spec_hash=spec_digest, db_snapshot=snap,
        )  # fmt: skip
        try:
            self.session.add(cp)
            await self.session.flush()
        except BaseException:
            await self._drop_dbs([snap])
            raise
        return cp

    async def checkpoint(
        self, project_id: uuid.UUID, ws_id: uuid.UUID, label: str
    ) -> CheckpointRead:
        self._root()
        prev, _, _ = await self._claim(project_id, ws_id, "checkpointing")
        try:
            ws = await self._get(project_id, ws_id)
            cp = await self._take_checkpoint(ws, label)
            ws.state = "active"
            out = checkpoint_read(cp)
            await self.session.commit()
        except BaseException:
            await self.session.rollback()
            await self._release(project_id, ws_id, prev)
            raise
        return out

    async def rollback(
        self, project_id: uuid.UUID, ws_id: uuid.UUID, checkpoint_id: uuid.UUID
    ) -> WorkspaceRead:
        self._root()
        prev, wt, db = await self._claim(project_id, ws_id, "rolling_back")
        tmp = f"bbtmp_{uuid.uuid4().hex}"
        try:
            cp = (
                await self.session.execute(
                    select(WorkspaceCheckpoint).where(
                        WorkspaceCheckpoint.id == checkpoint_id,
                        WorkspaceCheckpoint.workspace_id == ws_id,
                    )
                )
            ).scalar_one_or_none()
            if cp is None or not cp.db_snapshot:
                raise AppError("not_found", "checkpoint not found", 404)
            sha, snap, seq = cp.git_sha, cp.db_snapshot, cp.spec_seq
            # 1. everything that can fail without changing anything
            await self._git(wt, "cat-file", "-e", f"{sha}^{{commit}}")
            await self._admin(*self._clone(tmp, snap, kick=False))
            # 2. code (one atomic ref move), then 3. data swap
            await self._git(wt, "reset", "-q", "--hard", sha)
            await self._git(wt, "clean", "-q", "-fdx")
            try:
                await self._admin(
                    self._kick(db),
                    f'DROP DATABASE IF EXISTS "{db}"',
                    f'ALTER DATABASE "{tmp}" RENAME TO "{db}"',
                )
            except BaseException:
                log.error("rollback data swap failed; restoring preview db from snapshot")
                await self._admin(*self._clone(db, snap, kick=False))
                raise
            await self._release(project_id, ws_id, "rolled_back", spec_seq=seq)
        except BaseException:
            await self.session.rollback()
            await self._drop_dbs([tmp])
            await self._release(project_id, ws_id, prev)
            raise
        return await self.read(project_id, ws_id)

    # -- discard ---------------------------------------------------------------------------
    async def _drop_dbs(self, names: list[str]) -> list[str]:
        failed = []
        for name in names:
            try:
                await self._admin(self._kick(name), f'DROP DATABASE IF EXISTS "{name}"')
            except Exception:
                log.exception("could not drop database %s", name)
                failed.append(name)
        return failed

    async def _cleanup(
        self, project_id: uuid.UUID, wt: Path, branch: str, db: str, snaps: list[str]
    ) -> tuple[bool, list[str]]:
        """Every step independent; returns (worktree removed, databases that could NOT be
        dropped). Failures are logged, never raised, and never forgotten by the caller."""
        repo = self._repo(project_id)
        try:
            if wt.exists():
                await self._git(repo, "worktree", "remove", "--force", str(wt))
        except Exception:
            log.exception("worktree remove failed")
        shutil.rmtree(wt, ignore_errors=True)
        for args in (("worktree", "prune"), ("branch", "-q", "-D", branch)):
            try:
                await self._git(repo, *args)
            except Exception:
                log.warning("git %s failed during cleanup", args[0])
        failed = await self._drop_dbs([db, *snaps])
        return (not wt.exists()), failed

    async def discard(self, project_id: uuid.UUID, ws_id: uuid.UUID) -> WorkspaceRead:
        self._root()
        ws = await self._get(project_id, ws_id, lock=True)
        if ws.state in BUSY_STATES and datetime.now(UTC) - ws.updated_at <= BUSY_STALE:
            raise AppError("workspace_busy", "another operation is running on this workspace", 409)
        if ws.state == "discarded" and ws.preview_db_name is None and ws.worktree_path is None:
            return await self.read(project_id, ws_id)
        ws.state = "discarded"  # write-ahead: nothing new can start from here
        await self.session.commit()
        ws = await self._get(project_id, ws_id, lock=True)
        cps = await self._checkpoints(ws_id)
        wt, db, branch = ws.worktree_path, ws.preview_db_name, ws.branch
        snaps = [c.db_snapshot for c in cps if c.db_snapshot]
        wt_ok, failed = await self._cleanup(
            project_id, Path(wt) if wt else self._root() / "none", branch, db or "bbws_none", snaps
        )
        if wt_ok:
            ws.worktree_path = None
        if db and db not in failed:
            ws.preview_db_name = None
        for c in cps:
            if c.db_snapshot and c.db_snapshot not in failed:
                c.db_snapshot = None
        if not wt_ok or failed:
            log.error("workspace %s discarded with incomplete cleanup", ws_id)
        await self.session.commit()
        return await self.read(project_id, ws_id)
