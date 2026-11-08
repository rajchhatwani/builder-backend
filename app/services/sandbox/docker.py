"""DockerSandbox: the Sandbox interface over the docker CLI (asyncio subprocess, no extra deps).

Isolation set, all verified in CP-B-SPIKE-FORGE under runsc/gVisor: `--runtime` from config,
per-sandbox `--internal` network (no egress), read-only root, tmpfs /tmp, cap-drop ALL,
no-new-privileges, non-root user, cpu/memory/pids caps, no swap. The only mount is one
read-only code directory. The docker socket is never mounted and `--privileged` is never used
(nothing in this module can produce either: see build_run_args).
"""

import asyncio
import contextlib
import json
import os
import re
import time
import uuid
from collections.abc import Collection

from app.config import Settings, get_settings
from app.services.sandbox.base import (
    ENV_RE,
    ID_RE,
    LABEL,
    LABEL_EXPIRES,
    LABEL_ID,
    MAX_OUTPUT_BYTES,
    RESERVED_ENV,
    Limits,
    ReapResult,
    RunResult,
    Sandbox,
    SandboxError,
    SandboxSpec,
    expiry_epoch,
    parse_size,
)

_IMAGE_RE = re.compile(r"^[a-z0-9][a-z0-9._/:@-]{0,254}$")
_HOST_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,62}$")
_IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_PATH_RE = re.compile(r"^/[A-Za-z0-9._/-]{0,200}$")
_NET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
_BAD_NETS = frozenset({"host", "none", "bridge", "default", "ingress", "docker_gwbridge"})
_BAD_TMPFS = ("/proc", "/dev", "/sys", "/workspace", "/tmp", "/etc", "/run")  # noqa: S108
MAX_EXTRA_TMPFS_BYTES = 1024**3
_USER_RE = re.compile(r"^\d{1,10}(:\d{1,10})?$")
_CLI_ENV_KEYS = (
    "PATH",
    "HOME",
    "DOCKER_HOST",
    "DOCKER_CONFIG",
    "XDG_RUNTIME_DIR",
    "DOCKER_CONTEXT",
)
CODE_MOUNT = "/workspace"


def name_for(sandbox_id: str) -> str:
    if not ID_RE.match(sandbox_id):
        raise SandboxError("invalid sandbox id")
    return f"bbsbx-{sandbox_id}"


def _validate(spec: SandboxSpec, allowed_images: Collection[str] | None = None) -> None:
    spec.limits.validate()
    name_for(spec.sandbox_id)
    if spec.network_owner is not None:
        name_for(spec.network_owner)
    if spec.tmpfs_uid is not None and not (1 <= spec.tmpfs_uid <= 65535):
        raise SandboxError("tmpfs_uid must be a non-root uid")
    if not _IMAGE_RE.match(spec.image):
        raise SandboxError("invalid image reference")
    allowed = get_settings().sandbox_images if allowed_images is None else allowed_images
    if spec.image not in allowed:
        raise SandboxError("image is not on the sandbox allowlist")
    if not _USER_RE.match(spec.user) or spec.user.split(":")[0] in ("0", "root"):
        raise SandboxError("sandbox user must be a non-root numeric uid[:gid]")
    if spec.network is not None and (
        not _NET_RE.match(spec.network) or spec.network.lower() in _BAD_NETS
    ):
        raise SandboxError("invalid network name")
    for k in spec.env:
        if (
            not ENV_RE.match(k)
            or k in RESERVED_ENV
            or k in _CLI_ENV_KEYS
            or k.startswith(("DOCKER_", "BB_SANDBOX"))
        ):
            raise SandboxError(f"environment variable name not allowed: {k!r}")
    for host, ip in spec.extra_hosts.items():
        if not _HOST_RE.match(host) or not _IP_RE.match(ip):
            raise SandboxError("extra_hosts must map a simple hostname to an IPv4 address")
    for path, size in spec.tmpfs.items():
        if not _PATH_RE.match(path) or ".." in path or path == "/":
            raise SandboxError(f"invalid tmpfs path {path!r}")
        if parse_size(size) > MAX_EXTRA_TMPFS_BYTES:
            raise SandboxError("tmpfs size too large")
        if any(path == b or path.startswith(b + "/") for b in _BAD_TMPFS):
            raise SandboxError(f"tmpfs not allowed over {path!r}")
    if spec.code_dir is not None:
        resolved = spec.code_dir.resolve()
        if not resolved.is_dir():
            raise SandboxError("code_dir must be an existing directory")
        # Only reached by a caller bug, but the socket must never be mountable by accident.
        if "docker.sock" in str(resolved) or "," in str(resolved):
            raise SandboxError("code_dir not allowed")


def build_run_args(
    spec: SandboxSpec,
    runtime: str,
    network: str,
    now: float | None = None,
    allowed_images: Collection[str] | None = None,
) -> list[str]:
    """The `docker run` argument list (without the leading `docker`). Pure; unit-tested."""
    _validate(spec, allowed_images)
    if not _NET_RE.match(network) or network.lower() in _BAD_NETS:
        raise SandboxError("invalid network name")
    lim: Limits = spec.limits
    name = name_for(spec.sandbox_id)
    args = [
        "run",
        "-d",
        "--name",
        name,
        "--pull",
        "never",
        "--runtime",
        runtime,
        "--network",
        network,
        "--read-only",
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,nodev,size={lim.tmpfs_size}",  # noqa: S108 (container path)
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        str(lim.pids),
        "--memory",
        lim.memory,
        "--memory-swap",
        lim.memory,  # == memory: no swap
        "--cpus",
        str(lim.cpus),
        "--ulimit",
        "nofile=1024:1024",
        "--user",
        spec.user,
        "--stop-timeout",
        "5",
        "--log-driver",
        "json-file",
        "--log-opt",
        "max-size=1m",
        "--log-opt",
        "max-file=1",
        "--label",
        f"{LABEL}=1",
        "--label",
        f"{LABEL_ID}={spec.sandbox_id}",
        "--label",
        f"{LABEL_EXPIRES}={expiry_epoch(lim, now)}",
    ]
    for path, size in sorted(spec.tmpfs.items()):
        owner = ""
        if spec.tmpfs_uid:
            mode = "0700" if path.startswith("/var/lib/") else "0755"  # data dir vs run dir
            owner = f",uid={spec.tmpfs_uid},gid={spec.tmpfs_uid},mode={mode}"
        args += ["--tmpfs", f"{path}:rw,nosuid,nodev,size={size}{owner}"]
    for host, ip in sorted(spec.extra_hosts.items()):
        args += ["--add-host", f"{host}:{ip}"]
    if spec.code_dir is not None:
        args += [
            "--mount",
            f"type=bind,source={spec.code_dir.resolve()},target={CODE_MOUNT},readonly",
            "--workdir",
            CODE_MOUNT,
        ]
    for key in sorted(spec.env):
        args += ["-e", key]  # value travels in the CLI's environment, never on the command line
    args.append(spec.image)
    args += list(spec.command or [])
    return args


class DockerSandbox(Sandbox):
    def __init__(self, settings: Settings | None = None, docker_bin: str | None = None) -> None:
        s = settings or get_settings()
        self.runtime = s.sandbox_runtime
        self.docker = docker_bin or s.sandbox_docker_bin
        # runc has no user-space kernel: allowed only when the environment is EXPLICITLY local
        # or test. An unset environment (which defaults to "local") never qualifies (S2-006).
        self._allow_runc = s.environment_explicit and s.environment in ("local", "test")
        self._runtime_ok = False
        self.images = frozenset(s.sandbox_images)

    # -- docker CLI ------------------------------------------------------------------------
    def _cli_env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = {k: os.environ[k] for k in _CLI_ENV_KEYS if k in os.environ}
        env.update(extra or {})
        return env

    async def _docker(
        self,
        *args: str,
        timeout: float = 60,
        env: dict[str, str] | None = None,
        cap: int = MAX_OUTPUT_BYTES,
    ) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            self.docker,
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._cli_env(env),
        )
        try:
            out, err = await asyncio.wait_for(
                asyncio.gather(_read_capped(proc.stdout, cap), _read_capped(proc.stderr, cap)),
                timeout,
            )
            rc = await asyncio.wait_for(proc.wait(), timeout)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
            raise
        return rc, out, err

    async def check_runtime(self) -> None:
        """Fail closed: the configured runtime must be registered; runc only in local/test."""
        if self._runtime_ok:
            return
        if self.runtime == "runc" and not self._allow_runc:
            raise SandboxError("runtime 'runc' is not isolated enough outside local/test")
        if not re.fullmatch(r"[a-z0-9_.-]{1,40}", self.runtime):
            raise SandboxError("invalid sandbox runtime name")
        rc, out, _ = await self._docker("info", "--format", "{{json .Runtimes}}")
        if rc != 0:
            raise SandboxError("docker is not available")
        try:
            runtimes = json.loads(out)
        except ValueError as exc:
            raise SandboxError("could not read docker runtimes") from exc
        if self.runtime not in runtimes:
            raise SandboxError(f"sandbox runtime {self.runtime!r} is not registered with docker")
        self._runtime_ok = True

    async def _ensure_owned_internal(self, network: str, sandbox_id: str) -> None:
        """A supplied network must be --internal AND created for this very sandbox id."""
        rc, out, _ = await self._docker(
            "network", "inspect", network, "--format",
            '{{.Internal}}|{{index .Labels "bb.sandbox.id"}}',
        )  # fmt: skip
        internal, _, owner = out.strip().partition("|")
        if rc != 0 or internal != "true" or owner != sandbox_id:
            raise SandboxError("sandbox network must be an internal network owned by this sandbox")

    async def create_network(self, sandbox_id: str, limits: Limits | None = None) -> str:
        """Create the --internal, labelled network for one sandbox id; returns its name."""
        name = name_for(sandbox_id)
        expires = expiry_epoch(limits or Limits())
        rc, _, err = await self._docker(
            "network", "create", "--internal",
            "--label", f"{LABEL}=1",
            "--label", f"{LABEL_ID}={sandbox_id}",
            "--label", f"{LABEL_EXPIRES}={expires}",
            name,
        )  # fmt: skip
        if rc != 0:
            raise SandboxError(f"could not create sandbox network: {err.strip()[:200]}")
        return name

    # -- lifecycle -------------------------------------------------------------------------
    async def start(self, spec: SandboxSpec) -> str:
        await self.check_runtime()
        _validate(spec, self.images)
        name_for(spec.sandbox_id)
        created_net = False
        if spec.network is None:
            net = await self.create_network(spec.sandbox_id, spec.limits)
            created_net = True
        else:
            net = spec.network
            await self._ensure_owned_internal(net, spec.network_owner or spec.sandbox_id)
        args = build_run_args(spec, self.runtime, net, allowed_images=self.images)
        rc, _, err = await self._docker(*args, env=dict(spec.env))
        if rc != 0:
            if created_net:
                await self._docker("network", "rm", net)
            raise SandboxError(f"could not start sandbox: {err.strip()[:200]}")
        return spec.sandbox_id

    async def _state(self, sandbox_id: str) -> dict[str, object] | None:
        rc, out, _ = await self._docker(
            "inspect", "--format", "{{json .State}}", name_for(sandbox_id)
        )
        if rc != 0:
            return None
        try:
            state: dict[str, object] = json.loads(out)
        except ValueError:
            return None
        return state

    async def logs(self, sandbox_id: str, tail: int = 2000, since: str | None = None) -> str:
        args = ["logs", "--tail", str(max(1, min(tail, 2000)))]
        if since is not None:
            args += ["--since", since]
        rc, out, err = await self._docker(*args, name_for(sandbox_id))
        return out + err if rc == 0 else ""

    async def is_running(self, sandbox_id: str) -> bool:
        state = await self._state(sandbox_id)
        return bool(state and state.get("Running"))

    async def ip_of(self, sandbox_id: str, network: str) -> str | None:
        """The container's address on `network` (embedded DNS does not work under runsc)."""
        if not _NET_RE.match(network):
            raise SandboxError("invalid network name")
        rc, out, _ = await self._docker(
            "inspect", "--format", f'{{{{(index .NetworkSettings.Networks "{network}").IPAddress}}}}',
            name_for(sandbox_id),
        )  # fmt: skip
        ip = out.strip()
        return ip if rc == 0 and _IP_RE.match(ip) else None

    async def run(self, spec: SandboxSpec) -> RunResult:
        started = time.monotonic()
        sid = await self.start(spec)
        name = name_for(sid)
        timed_out = False
        try:
            try:
                await self._docker("wait", name, timeout=spec.limits.wall_seconds)
            except TimeoutError:
                timed_out = True
                await self._docker("kill", name)
            state = await self._state(sid)
            rc, out, err = await self._docker("logs", "--tail", "2000", name)
            return RunResult(
                sandbox_id=sid,
                exit_code=int(state["ExitCode"]) if state else None,  # type: ignore[call-overload]
                stdout=out,
                stderr=err,
                timed_out=timed_out,
                oom_killed=bool(state and state.get("OOMKilled")),
                died=state is None,
                duration_seconds=time.monotonic() - started,
            )
        finally:
            await self.destroy(sid)

    async def exec(self, sandbox_id: str, argv: list[str], timeout: float) -> RunResult:
        name = name_for(sandbox_id)
        started = time.monotonic()
        timeout = max(0.1, min(timeout, 3600))
        state = await self._state(sandbox_id)
        if state is None or not state.get("Running"):
            return RunResult(sandbox_id, None, "", "", died=True)
        try:
            rc, out, err = await self._docker("exec", name, *argv, timeout=timeout)
        except TimeoutError:
            # The exec'd process cannot be targeted from outside: kill the whole sandbox.
            await self._docker("kill", name)
            return RunResult(
                sandbox_id,
                None,
                "",
                "",
                timed_out=True,
                duration_seconds=time.monotonic() - started,
            )
        died = rc != 0 and "is not running" in err
        return RunResult(
            sandbox_id, rc, out, err, died=died, duration_seconds=time.monotonic() - started
        )

    async def stop(self, sandbox_id: str) -> None:
        await self._docker("stop", "-t", "5", name_for(sandbox_id), timeout=30)

    async def destroy(self, sandbox_id: str) -> None:
        name = name_for(sandbox_id)
        await self._docker("rm", "-f", "-v", name)
        # Only the network this sandbox created (it carries our label); rm fails harmlessly
        # for a network that does not exist.
        rc, out, _ = await self._docker(
            "network", "ls", "-q", "--filter", f"label={LABEL_ID}={sandbox_id}"
        )
        if rc == 0:
            for net_id in out.split():
                await self._docker("network", "rm", net_id)

    async def reap(self, now: float | None = None) -> ReapResult:
        t = time.time() if now is None else now
        result = ReapResult()
        rc, out, _ = await self._docker(
            "ps", "-a", "--filter", f"label={LABEL}=1", "--format",
            '{{.ID}}|{{.State}}|{{.Label "bb.sandbox.expires"}}',
        )  # fmt: skip
        if rc != 0:
            raise SandboxError("reaper could not list sandbox containers")
        for line in out.splitlines():
            cid, _, rest = line.partition("|")
            state, _, expires = rest.partition("|")
            expired = expires.isdigit() and int(expires) <= t
            if expired or state in ("exited", "dead"):
                await self._docker("rm", "-f", "-v", cid)
                result.containers.append(cid)
        # Networks we created: remove when expired or when no container is left on them.
        rc, out, _ = await self._docker(
            "network", "ls", "--filter", f"label={LABEL}=1", "--format",
            '{{.ID}}|{{.Label "bb.sandbox.expires"}}',
        )  # fmt: skip
        if rc == 0:
            for line in out.splitlines():
                nid, _, expires = line.partition("|")
                rc2, members, _ = await self._docker(
                    "network", "inspect", nid, "--format", "{{len .Containers}}"
                )
                empty = rc2 == 0 and members.strip() == "0"
                expired = expires.isdigit() and int(expires) <= t
                if empty or expired:
                    rc3, _, _ = await self._docker("network", "rm", nid)
                    if rc3 == 0:
                        result.networks.append(nid)
        return result


async def _read_capped(stream: asyncio.StreamReader | None, cap: int) -> str:
    """Read to EOF but keep at most `cap` bytes (hostile output must not fill host memory)."""
    if stream is None:
        return ""
    buf = bytearray()
    while chunk := await stream.read(65536):
        if len(buf) < cap:
            buf += chunk[: cap - len(buf)]
    return buf.decode("utf-8", "replace")


def new_sandbox_id() -> str:
    return uuid.uuid4().hex[:16]


__all__ = ["CODE_MOUNT", "DockerSandbox", "build_run_args", "name_for", "new_sandbox_id"]


async def reap_expired(settings: Settings | None = None) -> ReapResult:
    """Scheduling hook for the preview runtime: call every `sandbox_reap_interval_seconds`.
    Raises SandboxError when the daemon cannot be listed, so the caller can alert."""
    box = DockerSandbox(settings)
    await box.check_runtime()
    return await box.reap()
