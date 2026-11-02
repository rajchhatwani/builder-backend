"""Preview runtime service (B3-10).

A preview is an API-only copy of a project (generated code + seeded Postgres) running in
sandboxes. This module holds the state machine, the access token, the effective-limits lookup,
the lifecycle operations and the expiry sweep. Docker is only touched through DockerSandbox
(runsc, no egress, image allowlist, never pulled).

Lifecycle: starting -> running -> sleeping (idle) -> starting (wake) -> running ... ->
expired (delete-after days; data wiped) | failed | killed.
Sleep tears the stack down; wake rebuilds it and re-seeds, so rows created inside a preview do
not survive a sleep (documented limit, preview data is disposable by design).
"""

import asyncio
import hashlib
import hmac
import logging
import secrets
import shutil
import time
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.core.generator import InvalidSpecError, generate
from app.core.generator.base import FileTree
from app.core.spec_models import spec_hash
from app.db import get_session_factory
from app.exceptions import AppError
from app.models.enums import AuditResult
from app.models.platform import PlatformUser
from app.models.preview import (
    LIVE_STATES,
    Preview,
    PreviewOrgLimits,
    PreviewPlatformSettings,
)
from app.models.project import Project
from app.models.workspace import Workspace
from app.schemas.preview import PreviewCreated, PreviewRead
from app.services import audit_service, preview_runtime
from app.services.preview_limits import Effective, effective
from app.services.sandbox import DockerSandbox, reap_expired
from app.services.spec_service import SpecService

log = logging.getLogger(__name__)

TRANSITIONS: dict[str, frozenset[str]] = {
    "starting": frozenset({"running", "failed", "killed", "expired"}),
    # Teardown happens while "stopping"; only when it is finished does the preview become
    # "sleeping", so a wake can never overlap a teardown of the same sandbox names.
    "running": frozenset({"stopping", "killed", "expired", "failed"}),
    "stopping": frozenset({"sleeping", "killed", "expired", "failed"}),
    "sleeping": frozenset({"starting", "killed", "expired"}),
    "failed": frozenset({"killed", "expired"}),
    "expired": frozenset(),
    "killed": frozenset(),
}
STARTING_STALE = timedelta(minutes=5)
TOUCH_EVERY_SECONDS = 20.0
_TOKEN_PREFIX = "bbp_"

_tasks: set[asyncio.Task[None]] = set()
_last_touch: dict[uuid.UUID, float] = {}

# Tests replace these two; production uses the real session factory and DockerSandbox.
SessionFactory = Callable[[], async_sessionmaker[AsyncSession]]
session_factory: SessionFactory = get_session_factory


def get_sandbox(settings: Settings | None = None) -> DockerSandbox:
    return DockerSandbox(settings or get_settings())


# -- pure helpers -------------------------------------------------------------------------


def can_transition(old: str, new: str) -> bool:
    return new in TRANSITIONS.get(old, frozenset())


def new_token() -> str:
    return _TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    # The token carries 256 bits of entropy, so a plain SHA-256 is enough (no stretching needed).
    return hashlib.sha256(token.encode()).hexdigest()


def token_matches(stored_hash: str | None, presented: str | None) -> bool:
    """Constant-time. Compares against a dummy hash when there is nothing stored so a missing
    preview and a wrong token take the same path."""
    candidate = hash_token(presented or "")
    expected = stored_hash or hash_token("-" * 8)
    ok = hmac.compare_digest(candidate, expected)
    return ok and stored_hash is not None and presented is not None


def _now() -> datetime:
    return datetime.now(UTC)


def preview_read(p: Preview) -> PreviewRead:
    return PreviewRead(
        id=p.id,
        project_id=p.project_id,
        workspace_id=p.workspace_id,
        state=p.state,
        spec_hash=p.spec_hash,
        url_path=f"/previews/{p.id}/",
        error=p.error,
        created_at=p.created_at,
        last_request_at=p.last_request_at,
        expires_at=p.expires_at,
        limits={k: v for k, v in p.limits.items() if k != "seed_profile"},
    )


def _unavailable() -> AppError:
    return AppError("previews_unavailable", "previews are not configured", 503)


def _gone(p: Preview) -> AppError:
    return AppError("preview_gone", f"this preview is {p.state}", 410)


# -- limits -------------------------------------------------------------------------------


async def effective_limits(session: AsyncSession, organization_id: uuid.UUID | None) -> Effective:
    platform = await session.get(PreviewPlatformSettings, 1)
    org_row = None
    if organization_id is not None:
        org_row = (
            await session.execute(
                select(PreviewOrgLimits).where(PreviewOrgLimits.organization_id == organization_id)
            )
        ).scalar_one_or_none()
    return effective(
        platform.kill_switch if platform else False,
        platform.limits if platform else None,
        org_row.limits if org_row else None,
        org_row.enabled if org_row else True,
        org_row.allow_above_default if org_row else False,
    )


async def kill_switch_on(session: AsyncSession) -> bool:
    platform = await session.get(PreviewPlatformSettings, 1)
    return bool(platform and platform.kill_switch)


# -- runtime operations (own short sessions; safe to call from background tasks) ----------


async def _load(preview_id: uuid.UUID) -> Preview | None:
    async with session_factory()() as s:
        return await s.get(Preview, preview_id)


async def _claim(
    preview_id: uuid.UUID, from_states: tuple[str, ...], to_state: str, **values: object
) -> bool:
    """Atomically move a preview between states; False when it was not in `from_states`."""
    for old in from_states:
        if not can_transition(old, to_state):
            raise ValueError(f"illegal preview transition {old} -> {to_state}")
    now = _now()
    async with session_factory()() as s:
        res = await s.execute(
            update(Preview)
            .where(Preview.id == preview_id, Preview.state.in_(from_states))
            .values(state=to_state, state_since=now, updated_at=now, **values)
        )
        await s.commit()
        return (res.rowcount or 0) == 1  # type: ignore[attr-defined]


def _spawn(coro: Coroutine[object, object, None]) -> None:
    task = asyncio.ensure_future(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _wipe_code(p: Preview) -> None:
    if p.code_dir:
        shutil.rmtree(Path(p.code_dir).parent, ignore_errors=True)


async def launch_task(preview_id: uuid.UUID) -> None:
    """Build the stack for a preview in state `starting` and flip it to running/failed."""
    settings = get_settings()
    p = await _load(preview_id)
    if p is None or p.state != "starting" or not p.code_dir:
        return
    box = get_sandbox(settings)
    lim = p.limits
    remaining = int((p.expires_at - _now()).total_seconds())
    spec = preview_runtime.StackSpec(
        code_dir=Path(p.code_dir),
        db_sandbox=p.db_sandbox,
        app_sandbox=p.app_sandbox,
        cpus=float(lim.get("cpus", 0.5)),  # type: ignore[arg-type]
        memory_mb=int(lim.get("memory_mb", 512)),  # type: ignore[call-overload]
        db_mb=int(lim.get("db_mb", 1024)),  # type: ignore[call-overload]
        ttl_seconds=max(60, min(remaining, 30 * 86400)),
        seed_profile=lim.get("seed_profile") or None,  # type: ignore[arg-type]
    )
    try:
        ip = await preview_runtime.launch(box, spec, settings)
    except Exception as exc:  # noqa: BLE001 - any failure ends in `failed`, with a redacted note
        log.warning("preview %s failed to start: %s", preview_id, exc)
        msg = preview_runtime.redact(str(exc) or exc.__class__.__name__)[:300]
        await _claim(preview_id, ("starting",), "failed", error=msg, app_ip=None)
        return
    ok = await _claim(
        preview_id, ("starting",), "running", app_ip=ip, error=None, last_request_at=_now()
    )
    if not ok:  # killed / expired while it was starting
        await preview_runtime.teardown(box, p.db_sandbox, p.app_sandbox)


async def end_preview(preview_id: uuid.UUID, to_state: str, error: str | None = None) -> bool:
    """killed / expired: stop the stack, delete the code, forget the token."""
    p = await _load(preview_id)
    if p is None:
        return False
    ok = await _claim(
        preview_id, tuple(s for s in LIVE_STATES + ("failed",) if can_transition(s, to_state)),
        to_state, token_hash=None, app_ip=None, error=error,
    )  # fmt: skip
    if not ok:
        return False
    await preview_runtime.teardown(get_sandbox(), p.db_sandbox, p.app_sandbox)
    await asyncio.to_thread(_wipe_code, p)
    _last_touch.pop(preview_id, None)
    return True


async def sleep_preview(preview_id: uuid.UUID, error: str | None = None) -> bool:
    p = await _load(preview_id)
    if p is None or not await _claim(preview_id, ("running",), "stopping", app_ip=None):
        return False
    try:
        await preview_runtime.teardown(get_sandbox(), p.db_sandbox, p.app_sandbox)
    finally:
        # Only now may a request wake it. If it was killed/expired meanwhile this is a no-op.
        await asyncio.shield(_claim(preview_id, ("stopping",), "sleeping", error=error))
    return True


async def authenticate(preview_id: uuid.UUID, token: str | None) -> Preview:
    """The proxy's gate. 401 for a missing or wrong token or an unknown preview (same answer)."""
    p = await _load(preview_id)
    if p is None or not token_matches(p.token_hash, token):
        raise AppError("unauthorized", "a valid preview token is required", 401)
    return p


async def ensure_running(preview_id: uuid.UUID, timeout: float) -> Preview:
    """Return the preview once it is running, waking it first when it sleeps (~3s cold start)."""
    deadline = time.monotonic() + timeout
    while True:
        p = await _load(preview_id)
        if p is None or p.state in ("expired", "killed", "failed"):
            raise _gone(p) if p else AppError("not_found", "preview not found", 404)
        if p.state == "running" and p.app_ip:
            return p
        if p.state == "sleeping":
            async with session_factory()() as s:
                if await kill_switch_on(s):
                    raise AppError("previews_disabled", "previews are switched off", 503)
            if await _claim(
                preview_id, ("sleeping",), "starting", wake_count=p.wake_count + 1, error=None
            ):
                _spawn(launch_task(preview_id))
        if time.monotonic() > deadline:
            raise AppError("preview_waking", "the preview is still starting; retry shortly", 504)
        await asyncio.sleep(0.4)


async def touch(preview_id: uuid.UUID) -> None:
    """Record activity (throttled) so the idle timer restarts."""
    mono = time.monotonic()
    if mono - _last_touch.get(preview_id, 0.0) < TOUCH_EVERY_SECONDS:
        return
    _last_touch[preview_id] = mono
    async with session_factory()() as s:
        await s.execute(
            update(Preview).where(Preview.id == preview_id).values(last_request_at=_now())
        )
        await s.commit()


@dataclass
class SweepResult:
    slept: int = 0
    expired: int = 0
    killed: int = 0
    failed: int = 0
    healed: int = 0
    reaped_containers: int = 0
    reaped_networks: int = 0


async def sweep(now: datetime | None = None) -> SweepResult:
    """Idle sleep, expiry (data wipe), kill switch, stuck starts, dead containers, then the
    sandbox reaper. Safe to run from several processes (every change is a conditional claim)."""
    now = now or _now()
    settings = get_settings()
    out = SweepResult()
    async with session_factory()() as s:
        kill = await kill_switch_on(s)
        rows = list(
            (await s.execute(select(Preview).where(Preview.state.in_(LIVE_STATES)))).scalars()
        )
        off_projects = set(
            (
                await s.execute(
                    select(Project.id)
                    .join(PreviewOrgLimits, PreviewOrgLimits.organization_id == Project.organization_id)
                    .where(PreviewOrgLimits.enabled.is_(False))
                )
            ).scalars()
        )
    box = get_sandbox(settings)
    for p in rows:
        try:
            if now >= p.expires_at:
                out.expired += await end_preview(p.id, "expired")
            elif kill or p.project_id in off_projects:
                out.killed += await end_preview(p.id, "killed", "previews switched off")
            elif p.state == "stopping" and now - p.state_since > STARTING_STALE:
                # a crashed worker left a teardown half done: finish it
                await preview_runtime.teardown(box, p.db_sandbox, p.app_sandbox)
                await _claim(p.id, ("stopping",), "sleeping")
            elif p.state == "starting" and now - p.state_since > STARTING_STALE:
                out.failed += await _claim(
                    p.id, ("starting",), "failed", error="start timed out", app_ip=None
                )
                await preview_runtime.teardown(box, p.db_sandbox, p.app_sandbox)
            elif p.state == "running":
                idle = now - p.last_request_at
                if idle > timedelta(minutes=float(p.limits.get("sleep_after_minutes", 30))):  # type: ignore[arg-type]
                    out.slept += await sleep_preview(p.id)
                elif not await box.is_running(p.app_sandbox):
                    # Crashed or OOM-killed: drop to sleeping so the next request rebuilds it.
                    out.healed += await sleep_preview(p.id, "stopped unexpectedly; restarted")
        except Exception:  # noqa: BLE001 - one bad preview must not stop the sweep
            log.exception("preview sweep failed for %s", p.id)
    try:
        async with preview_runtime.NET_LOCK:
            reaped = await reap_expired(settings)
        out.reaped_containers, out.reaped_networks = len(reaped.containers), len(reaped.networks)
    except Exception:  # noqa: BLE001 - docker down: the sweep still did its database work
        log.exception("sandbox reaper failed")
    return out


_last_lazy: float = 0.0


def spawn_sweep() -> None:
    """Run a sweep in the background now (kill switch / org switch toggled)."""
    _spawn(_sweep_quiet())


async def _sweep_quiet() -> None:
    try:
        await sweep()
    except Exception:  # noqa: BLE001
        log.exception("preview sweep failed")


def maybe_sweep() -> None:
    """Without the scheduler, expiry / kill switch still act: preview API calls start a sweep
    at most once per sweep interval (per process)."""
    global _last_lazy  # noqa: PLW0603
    settings = get_settings()
    if settings.preview_scheduler_enabled or not settings.preview_lazy_sweep:
        return
    mono = time.monotonic()
    if mono - _last_lazy < settings.preview_sweep_interval_seconds:
        return
    _last_lazy = mono
    spawn_sweep()


async def ensure_enabled(project_id: uuid.UUID) -> None:
    """503 when the kill switch is on or the project's organization is switched off."""
    async with session_factory()() as s:
        org_id = (
            await s.execute(select(Project.organization_id).where(Project.id == project_id))
        ).scalar_one_or_none()
        eff = await effective_limits(s, org_id)
    if not eff.enabled:
        raise AppError("previews_disabled", "previews are switched off", 503)


async def scheduler_loop(interval: float) -> None:
    """Run sweep() forever. Started from the app lifespan when preview_scheduler_enabled."""
    while True:
        try:
            await sweep()
        except Exception:  # noqa: BLE001
            log.exception("preview sweep crashed")
        await asyncio.sleep(interval)


# -- API-side service ---------------------------------------------------------------------


class PreviewService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    def _root(self) -> Path:
        if not self.settings.preview_root:
            raise _unavailable()
        return Path(self.settings.preview_root).resolve()

    async def _project(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise AppError("not_found", "project not found", 404)
        return project

    async def _get(self, project_id: uuid.UUID, preview_id: uuid.UUID) -> Preview:
        p = await self.session.get(Preview, preview_id)
        if p is None or p.project_id != project_id:
            raise AppError("not_found", "preview not found", 404)
        return p

    async def list(self, project_id: uuid.UUID) -> list[PreviewRead]:
        maybe_sweep()
        rows = (
            await self.session.execute(
                select(Preview)
                .where(Preview.project_id == project_id)
                .order_by(Preview.created_at.desc())
                .limit(100)
            )
        ).scalars()
        return [preview_read(p) for p in rows]

    async def read(self, project_id: uuid.UUID, preview_id: uuid.UUID) -> PreviewRead:
        maybe_sweep()
        return preview_read(await self._get(project_id, preview_id))

    async def _render(self, project_id: uuid.UUID) -> tuple[str, str | None, FileTree]:
        # Deliberately NOT GenerationService._render: that injects the project's decrypted
        # provider secrets. A preview never receives real credentials.
        spec = await SpecService(self.session).assemble(project_id)
        try:
            files = generate(spec)
        except InvalidSpecError as exc:
            raise AppError(
                "spec_invalid",
                f"spec has {len(exc.issues)} validation issue(s); fix them to preview",
                422,
                [i.model_dump() for i in exc.issues],
            ) from exc
        names = sorted(p.name for p in spec.seed)
        profile = "demo" if "demo" in names else (names[0] if names else None)
        return spec_hash(spec), profile, files

    async def _workspace_files(
        self, project_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> Path:
        ws = await self.session.get(Workspace, workspace_id)
        if ws is None or ws.project_id != project_id:
            raise AppError("not_found", "workspace not found", 404)
        if ws.state not in ("active", "rolled_back") or not ws.worktree_path:
            raise AppError("workspace_not_ready", "that workspace cannot be previewed", 409)
        if not self.settings.workspace_root:
            raise AppError("workspaces_unavailable", "draft workspaces are not configured", 503)
        wt = Path(ws.worktree_path).resolve()
        if not wt.is_relative_to(Path(self.settings.workspace_root).resolve()) or not wt.is_dir():
            raise AppError("workspace_not_ready", "that workspace cannot be previewed", 409)
        return wt

    async def create(
        self, project_id: uuid.UUID, user: PlatformUser, workspace_id: uuid.UUID | None = None
    ) -> PreviewCreated:
        root = self._root()
        maybe_sweep()
        project = await self._project(project_id)
        eff = await effective_limits(self.session, project.organization_id)
        if not eff.enabled:
            raise AppError(
                "previews_disabled",
                "previews are switched off"
                + (" for this organization" if eff.reason == "org_disabled" else ""),
                503,
            )
        lim = eff.limits
        spec_h, profile, files = await self._render(project_id)
        src_dir = await self._workspace_files(project_id, workspace_id) if workspace_id else None

        # Quota under a per-user lock so two parallel requests cannot both slip under it.
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
            {"k": f"preview:{user.id}"},
        )
        live = (
            await self.session.execute(
                select(func.count())
                .select_from(Preview)
                .where(Preview.created_by == user.id, Preview.state.in_(LIVE_STATES))
            )
        ).scalar_one()
        if live >= lim.max_live_per_user:
            raise AppError(
                "preview_quota",
                f"you already have {live} live preview(s); the limit is {lim.max_live_per_user}",
                409,
            )
        token = new_token()
        pid = uuid.uuid4()
        code_dir = root / pid.hex / "code"
        now = _now()
        p = Preview(
            id=pid,
            project_id=project_id,
            workspace_id=workspace_id,
            created_by=user.id,
            state="starting",
            token_hash=hash_token(token),
            spec_hash=spec_h,
            db_sandbox=uuid.uuid4().hex[:16],
            app_sandbox=uuid.uuid4().hex[:16],
            code_dir=str(code_dir),
            limits={**lim.as_dict(), "seed_profile": profile},
            wake_count=0,
            created_at=now,
            updated_at=now,
            last_request_at=now,
            state_since=now,
            expires_at=now + timedelta(days=lim.delete_after_days),
        )
        self.session.add(p)
        await audit_service.record(
            self.session,
            action="preview.create",
            actor_id=user.id,
            actor_email=user.email,
            target_type="preview",
            target_id=pid,
            project_id=project_id,
            organization_id=project.organization_id,
            detail={"workspace": str(workspace_id) if workspace_id else None},
        )
        await self.session.commit()
        try:
            await asyncio.to_thread(self._write_code, code_dir, files, src_dir)
        except Exception as exc:  # noqa: BLE001
            log.exception("could not write preview code")
            await _claim(pid, ("starting",), "failed", error="could not write the code")
            await asyncio.to_thread(shutil.rmtree, root / pid.hex, True)
            raise AppError("preview_failed", "could not prepare the preview", 500) from exc
        _spawn(launch_task(pid))
        await self.session.refresh(p)
        return PreviewCreated(**preview_read(p).model_dump(), token=token)

    @staticmethod
    def _write_code(code_dir: Path, files: FileTree, src_dir: Path | None) -> None:
        code_dir.mkdir(parents=True, exist_ok=True)
        code_dir.parent.chmod(0o755)
        code_dir.chmod(0o755)
        if src_dir is not None:
            # symlinks=True copies links AS links (never their targets); they are then removed,
            # so nothing outside the worktree can end up inside the preview.
            shutil.copytree(
                src_dir, code_dir, dirs_exist_ok=True, symlinks=True,
                ignore=shutil.ignore_patterns(".git", ".gitattributes", ".gitmodules"),
            )  # fmt: skip
            for path in sorted(code_dir.rglob("*"), reverse=True):
                if path.is_symlink():
                    path.unlink()
            return
        for rel, content in files.items():
            target = (code_dir / rel).resolve()
            if not target.is_relative_to(code_dir.resolve()):
                raise ValueError("generated path escapes the code directory")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
            target.chmod(0o644)
        for d in code_dir.rglob("*"):
            if d.is_dir():
                d.chmod(0o755)

    async def kill(self, project_id: uuid.UUID, preview_id: uuid.UUID, user: PlatformUser) -> PreviewRead:
        p = await self._get(project_id, preview_id)
        project = await self._project(project_id)
        await end_preview(preview_id, "killed")
        await audit_service.record(
            self.session,
            action="preview.kill",
            actor_id=user.id,
            actor_email=user.email,
            target_type="preview",
            target_id=preview_id,
            project_id=project_id,
            organization_id=project.organization_id,
            result=AuditResult.ok,
        )
        await self.session.commit()
        await self.session.refresh(p)
        return preview_read(p)

    async def rotate_token(
        self, project_id: uuid.UUID, preview_id: uuid.UUID, user: PlatformUser
    ) -> PreviewCreated:
        p = await self._get(project_id, preview_id)
        if p.state not in LIVE_STATES:
            raise _gone(p)
        token = new_token()
        p.token_hash = hash_token(token)
        project = await self._project(project_id)
        await audit_service.record(
            self.session,
            action="preview.rotate_token",
            actor_id=user.id,
            actor_email=user.email,
            target_type="preview",
            target_id=preview_id,
            project_id=project_id,
            organization_id=project.organization_id,
        )
        await self.session.commit()
        return PreviewCreated(**preview_read(p).model_dump(), token=token)
