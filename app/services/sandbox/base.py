"""Sandbox interface and value types (B3-4). Nothing here talks to Docker.

A sandbox is where generated or AI-written code runs. Rules every implementation keeps:
egress denied, no host mounts except one read-only code mount, no docker socket, hard limits,
and "the sandbox died" is a normal outcome, never an exception the caller must special-case.
"""

import re
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

# Safe defaults from the CP-B spike (runsc/systrap): 0.5 CPU / 512 MB / 100 pids.
MAX_CPUS = 4.0
MAX_MEMORY_BYTES = 4 * 1024**3
MAX_PIDS = 1024
MAX_WALL_SECONDS = 3600
MAX_OUTPUT_BYTES = 64 * 1024
ID_RE = re.compile(r"^[a-f0-9]{8,32}$")
ENV_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")
# Env names that would change how the docker CLI itself behaves (we pass values via its env).
RESERVED_ENV = frozenset({"PATH", "HOME", "LD_PRELOAD", "LD_LIBRARY_PATH", "TMPDIR", "USER"})
_SIZE_RE = re.compile(r"^(\d{1,6})([kmg]?)$")
_UNITS = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
LABEL = "bb.sandbox"
LABEL_ID = "bb.sandbox.id"
LABEL_EXPIRES = "bb.sandbox.expires"


class SandboxError(Exception):
    """The sandbox could not be created or is not safe to use. Fail closed."""


def parse_size(value: str) -> int:
    m = _SIZE_RE.match(value.strip().lower())
    if not m or int(m.group(1)) == 0:
        raise SandboxError(f"invalid size {value!r} (use e.g. 64m, 512m, 1g)")
    return int(m.group(1)) * _UNITS[m.group(2)]


@dataclass(frozen=True)
class Limits:
    cpus: float = 0.5
    memory: str = "512m"
    pids: int = 100
    wall_seconds: int = 30  # one run()/exec() is killed after this
    tmpfs_size: str = "64m"  # the only writable scratch space besides explicit tmpfs mounts
    # Preview DB size (1 GB default) is enforced by the DB layer, not by the container; it is
    # carried here so one object describes a preview's whole budget.
    db_size: str = "1g"
    ttl_seconds: int = 3600  # after this the reaper removes the sandbox

    def validate(self) -> None:
        if not (0 < self.cpus <= MAX_CPUS):
            raise SandboxError(f"cpus must be in (0, {MAX_CPUS}]")
        if parse_size(self.memory) > MAX_MEMORY_BYTES or parse_size(self.memory) < 16 * 1024**2:
            raise SandboxError("memory must be between 16m and 4g")
        if not (1 <= self.pids <= MAX_PIDS):
            raise SandboxError(f"pids must be in [1, {MAX_PIDS}]")
        if not (1 <= self.wall_seconds <= MAX_WALL_SECONDS):
            raise SandboxError(f"wall_seconds must be in [1, {MAX_WALL_SECONDS}]")
        if not (1 <= self.ttl_seconds <= 30 * 86400):
            raise SandboxError("ttl_seconds must be in [1, 30 days]")
        if parse_size(self.tmpfs_size) > MAX_MEMORY_BYTES:
            raise SandboxError("tmpfs_size too large")
        parse_size(self.db_size)


@dataclass
class SandboxSpec:
    image: str
    command: list[str] | None = None  # None -> the image's default
    code_dir: Path | None = None  # mounted READ-ONLY at /workspace
    env: dict[str, str] = field(default_factory=dict)  # never put long-lived secrets here
    # name -> IP. Embedded DNS does not work under runsc, so peers are reached by address.
    extra_hosts: dict[str, str] = field(default_factory=dict)
    # Extra tmpfs mounts (absolute path -> size), e.g. a throwaway DB's data dir.
    tmpfs: dict[str, str] = field(default_factory=dict)
    # Join this existing network instead of creating one. Must be --internal (checked).
    network: str | None = None
    # Sandbox id that created the network above, when several sandboxes of one preview share it.
    # None -> this sandbox's own id. The label check in DockerSandbox still applies.
    network_owner: str | None = None
    # Owner uid/gid for the EXTRA tmpfs mounts (e.g. a Postgres data dir run as uid 70).
    tmpfs_uid: int | None = None
    user: str = "10001:10001"
    limits: Limits = field(default_factory=Limits)
    sandbox_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])


@dataclass
class RunResult:
    sandbox_id: str
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    oom_killed: bool = False
    died: bool = False  # container gone / stopped before we could ask (normal, not an error)
    duration_seconds: float = 0.0


@dataclass
class ReapResult:
    containers: list[str] = field(default_factory=list)
    networks: list[str] = field(default_factory=list)


def expiry_epoch(limits: Limits, now: float | None = None) -> int:
    return int((time.time() if now is None else now) + limits.ttl_seconds)


class Sandbox(ABC):
    @abstractmethod
    async def start(self, spec: SandboxSpec) -> str:
        """Create + start a long-lived sandbox; returns its id."""

    @abstractmethod
    async def run(self, spec: SandboxSpec) -> RunResult:
        """One-shot: start, wait at most limits.wall_seconds (then kill), collect, destroy."""

    @abstractmethod
    async def exec(self, sandbox_id: str, argv: list[str], timeout: float) -> RunResult:
        """Run a command inside a live sandbox. On timeout the whole sandbox is killed."""

    @abstractmethod
    async def logs(self, sandbox_id: str, tail: int = 2000, since: str | None = None) -> str: ...

    @abstractmethod
    async def stop(self, sandbox_id: str) -> None: ...

    @abstractmethod
    async def destroy(self, sandbox_id: str) -> None: ...

    @abstractmethod
    async def reap(self, now: float | None = None) -> ReapResult:
        """Remove expired sandboxes and dead ones (exited/dead), plus orphaned networks."""
