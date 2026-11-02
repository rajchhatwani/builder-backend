"""Preview stack launcher (B3-10): one Postgres + one generated API in DockerSandbox.

Both containers run under the sandbox runtime (runsc) on a per-preview --internal network, so
there is no egress. The database lives in a tmpfs sized to the DB limit (a real cap: writes fail
with ENOSPC) and dies with the container; "sleep" tears the stack down and "wake" rebuilds it
and re-seeds (CP-B spike: DB is reached by IP, never by service name).
"""

import asyncio
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import Settings
from app.services.sandbox import DockerSandbox, Limits, SandboxError, SandboxSpec

APP_PORT = 8000
DB_UID = 70  # postgres:alpine's postgres user
_PROFILE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
# Held while a new network exists but its first container does not yet; the reaper takes it too
# so it can never remove a network that is about to be used.
NET_LOCK = asyncio.Lock()
_LAUNCH_SLOTS = asyncio.Semaphore(3)  # at most this many stacks being built at once, per process
_REDACT = [
    (re.compile(r"(?im)\b(authorization|proxy-authorization|x-preview-token|cookie|set-cookie)\b\s*[:=]\s*.*$"), r"\1: [redacted]"),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*(?:\+\w+)?://[^:\s/@]+:)[^@\s]+(@)"), r"\1[redacted]\2"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"), "[redacted-jwt]"),
    (re.compile(r"\b(?:sk|pk|rk|whsec)_(?:live_|test_)?[A-Za-z0-9]{8,}"), "[redacted-key]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "[redacted-key]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "[redacted-key]"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[redacted-key]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "[redacted-key]"),
    (re.compile(r"\bbbp_[A-Za-z0-9_-]{20,}"), "[redacted-key]"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [redacted]"),
    (
        re.compile(
            r"(?i)\b([A-Za-z0-9_]*(?:password|passwd|secret|token|api[_-]?key)[A-Za-z0-9_]*)"
            r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&\"']+)"
        ),
        r"\1\2[redacted]",
    ),
]


def redact(text: str, secrets_in_use: tuple[str, ...] = ()) -> str:
    """Remove known secret values and anything that looks like a credential from log text."""
    for value in secrets_in_use:
        if value and len(value) >= 6:
            text = text.replace(value, "[redacted]")
    for pattern, repl in _REDACT:
        text = pattern.sub(repl, text)
    return text


@dataclass(frozen=True)
class StackSpec:
    code_dir: Path
    db_sandbox: str
    app_sandbox: str
    cpus: float
    memory_mb: int
    db_mb: int
    ttl_seconds: int
    seed_profile: str | None


def seed_command(profile: str | None) -> str:
    if profile is None:
        return ""
    if not _PROFILE_RE.match(profile):
        raise SandboxError("invalid seed profile name")
    return f" && python -m app.seed --profile {profile}"


def app_command(profile: str | None) -> list[str]:
    script = (
        "alembic upgrade head"
        + seed_command(profile)
        + f" && exec python -m uvicorn app.main:app --host 0.0.0.0 --port {APP_PORT}"
        " --no-server-header"
    )
    return ["sh", "-c", script]


def db_limits(spec: StackSpec) -> Limits:
    # tmpfs counts as memory under gVisor: give the DB container room for a full data dir.
    return Limits(
        cpus=min(spec.cpus, 1.0),
        memory=f"{spec.db_mb + 256}m",
        pids=200,
        tmpfs_size="64m",
        db_size=f"{spec.db_mb}m",
        ttl_seconds=spec.ttl_seconds,
    )


def app_limits(spec: StackSpec) -> Limits:
    return Limits(
        cpus=spec.cpus, memory=f"{spec.memory_mb}m", pids=100, ttl_seconds=spec.ttl_seconds
    )


async def teardown(box: DockerSandbox, db_sandbox: str, app_sandbox: str) -> None:
    """App first, then the database (it owns the network, which goes with it). Never raises:
    a sandbox that is already gone is the normal case."""
    for sid in (app_sandbox, db_sandbox):
        try:
            await box.destroy(sid)
        except (SandboxError, OSError, TimeoutError):
            continue


async def _wait_db(box: DockerSandbox, sandbox: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # TCP on loopback: the init-time temp server only listens on the unix socket.
        res = await box.exec(
            sandbox, ["pg_isready", "-h", "127.0.0.1", "-U", "app", "-d", "app"], timeout=5
        )
        if res.exit_code == 0:
            return
        if res.died:
            raise SandboxError("preview database exited during start")
        await asyncio.sleep(0.5)
    raise SandboxError("preview database did not become ready in time")


async def _wait_app(box: DockerSandbox, sandbox: str, ip: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
        while time.monotonic() < deadline:
            if not await box.is_running(sandbox):
                tail = redact((await box.logs(sandbox, tail=15)).strip())[-400:]
                raise SandboxError(f"preview app exited during start: {tail}")
            try:
                r = await client.get(f"http://{ip}:{APP_PORT}/health")
                if r.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.4)
    raise SandboxError("preview app did not become ready in time")


async def launch(box: DockerSandbox, spec: StackSpec, settings: Settings) -> str:
    """Start the stack; returns the app container's address. Cleans up after itself on failure."""
    async with _LAUNCH_SLOTS:
        password = secrets.token_urlsafe(18)
        try:
            await box.check_runtime()
            limits = Limits(ttl_seconds=spec.ttl_seconds)
            async with NET_LOCK:
                net = await box.create_network(spec.db_sandbox, limits)
                await _start_db(box, spec, settings, net, password)
            await _wait_db(box, spec.db_sandbox, timeout=settings.preview_wake_timeout_seconds)
            db_ip = await box.ip_of(spec.db_sandbox, net)
            if db_ip is None:
                raise SandboxError("could not resolve the preview database address")
            await box.start(
                SandboxSpec(
                    image=settings.preview_app_image,
                    sandbox_id=spec.app_sandbox,
                    network=net,
                    network_owner=spec.db_sandbox,
                    code_dir=spec.code_dir,
                    extra_hosts={"db": db_ip},
                    env={
                        "DATABASE_URL": f"postgresql+asyncpg://app:{password}@db:5432/app",
                        "APP_ENV": "preview",
                        "PYTHONDONTWRITEBYTECODE": "1",
                        "PYTHONUNBUFFERED": "1",
                        "LOG_LEVEL": "INFO",
                        "CORS_ORIGINS": '["*"]',
                    },
                    command=app_command(spec.seed_profile),
                    limits=app_limits(spec),
                )
            )
            ip = await box.ip_of(spec.app_sandbox, net)
            if ip is None:
                raise SandboxError("could not resolve the preview app address")
            await _wait_app(box, spec.app_sandbox, ip, timeout=settings.preview_wake_timeout_seconds)
            return ip
        except BaseException:
            await asyncio.shield(teardown(box, spec.db_sandbox, spec.app_sandbox))
            raise


async def _start_db(
    box: DockerSandbox, spec: StackSpec, settings: Settings, net: str, password: str
) -> None:
    await box.start(
        SandboxSpec(
            image=settings.preview_db_image,
            sandbox_id=spec.db_sandbox,
            network=net,
            user=f"{DB_UID}:{DB_UID}",
            tmpfs_uid=DB_UID,
            tmpfs={
                "/var/lib/postgresql/data": f"{spec.db_mb}m",
                "/var/run/postgresql": "8m",
            },
            env={
                "POSTGRES_USER": "app",
                "POSTGRES_PASSWORD": password,
                "POSTGRES_DB": "app",
            },
            command=[
                "-c", "listen_addresses=*", "-c", "max_connections=40",
                "-c", "shared_buffers=32MB", "-c", "fsync=off",
                "-c", "synchronous_commit=off", "-c", "min_wal_size=32MB",
                "-c", "max_wal_size=64MB",
            ],  # fmt: skip
            limits=db_limits(spec),
        )
    )
