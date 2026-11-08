"""B3-4: the sandbox against hostile code, under gVisor (runsc). Needs Docker + the runsc runtime.

Each test runs a small Python "hook" inside DockerSandbox and asserts the limit held. Containers
and networks carry the bb.sandbox label; the module fixture reaps whatever a failed test leaves.
"""

import json
import shutil
import subprocess
import textwrap
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.config import Settings
from app.services.sandbox import DockerSandbox, Limits, SandboxSpec

IMAGE = "python:3.12-slim"


def _have_runsc() -> bool:
    if shutil.which("docker") is None:
        return False
    out = subprocess.run(
        ["docker", "info", "--format", "{{json .Runtimes}}"], capture_output=True, text=True
    )
    return out.returncode == 0 and "runsc" in out.stdout


pytestmark = pytest.mark.skipif(not _have_runsc(), reason="needs docker with the runsc runtime")


@pytest.fixture
async def box() -> AsyncIterator[DockerSandbox]:
    b = DockerSandbox(Settings(environment="test", sandbox_runtime="runsc"))
    yield b
    await b.reap(now=time.time() + 10**7)  # everything we labelled, expired or not


def py(code: str, **kw: object) -> SandboxSpec:
    return SandboxSpec(image=IMAGE, command=["python", "-c", textwrap.dedent(code)], **kw)  # type: ignore[arg-type]


async def test_no_outbound_network(box: DockerSandbox) -> None:
    r = await box.run(
        py(
            """
            import socket
            for host, port in (("1.1.1.1", 443), ("169.254.169.254", 80)):
                s = socket.socket(); s.settimeout(3)
                try:
                    s.connect((host, port)); print("CONNECTED", host)
                except OSError:
                    print("BLOCKED", host)
            try:
                socket.gethostbyname("example.com"); print("DNS-OK")
            except OSError:
                print("DNS-BLOCKED")
            """
        )
    )
    assert "CONNECTED" not in r.stdout and "DNS-OK" not in r.stdout, r.stdout
    assert r.stdout.count("BLOCKED") >= 2 and "DNS-BLOCKED" in r.stdout


async def test_root_fs_read_only_tmpfs_writable_no_socket(
    box: DockerSandbox, tmp_path: Path
) -> None:
    (tmp_path / "app.py").write_text("x = 1\n")
    r = await box.run(
        py(
            """
            import os
            def can(path, mode="w"):
                try:
                    open(path, mode).close(); return True
                except OSError:
                    return False
            print("root", can("/evil"), "etc", can("/etc/evil"))
            print("workspace", can("/workspace/evil"), "app", can("/workspace/app.py", "a"))
            print("tmp", can("/tmp/ok"))
            print("sock", os.path.exists("/var/run/docker.sock"))
            print("uid", os.getuid())
            """,
            code_dir=tmp_path,
        )
    )
    assert "root False etc False" in r.stdout, r.stdout + r.stderr
    assert "workspace False app False" in r.stdout and "tmp True" in r.stdout
    assert "sock False" in r.stdout and "uid 10001" in r.stdout
    assert not (tmp_path / "evil").exists()


async def test_memory_hog_is_oom_killed(box: DockerSandbox) -> None:
    r = await box.run(
        py(
            "b = []\nwhile True: b.append(bytearray(20*1024*1024))\n",
            limits=Limits(memory="128m", wall_seconds=60),
        )
    )
    assert r.oom_killed or r.exit_code == 137, (r.exit_code, r.stderr)
    assert not r.timed_out


async def test_pids_bomb_is_contained(box: DockerSandbox) -> None:
    r = await box.run(
        py(
            """
            import os, time
            n = 0
            try:
                for _ in range(2000):
                    if os.fork() == 0:
                        time.sleep(30); os._exit(0)
                    n += 1
            except OSError:
                print("LIMITED", n)
            print("SURVIVED", n)
            """,
            limits=Limits(pids=50, wall_seconds=20),
        )
    )
    # Either fork() is refused at the cap, or the whole sandbox is killed (spike: exit 2).
    assert "SURVIVED 2000" not in r.stdout
    if "LIMITED" in r.stdout:
        assert int(r.stdout.split("LIMITED")[1].split()[0]) <= 50
    else:
        assert r.exit_code != 0 or r.timed_out or r.died
    # Host is fine: the sandbox is gone and we can start another one.
    again = await box.run(py("print('alive')"))
    assert "alive" in again.stdout


async def test_cpu_is_throttled(box: DockerSandbox) -> None:
    r = await box.run(
        py(
            """
            import os, time
            t0 = time.time()
            kids = []
            for _ in range(4):
                pid = os.fork()
                if pid == 0:
                    while time.time() - t0 < 4: pass
                    os._exit(0)
                kids.append(pid)
            for k in kids: os.waitpid(k, 0)
            wall = time.time() - t0
            cpu = os.times().children_user + os.times().children_system
            print("RATIO", cpu / wall)
            """,
            limits=Limits(cpus=0.5, wall_seconds=30),
        )
    )
    ratio = float(r.stdout.split("RATIO")[1].split()[0])
    # 4 busy processes on 0.5 CPU: well under 1 CPU-second per second (4 unthrottled).
    assert ratio < 1.2, ratio


async def test_wall_time_kill(box: DockerSandbox) -> None:
    r = await box.run(py("import time; time.sleep(120)", limits=Limits(wall_seconds=3)))
    assert r.timed_out and r.duration_seconds < 20
    rc = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label=bb.sandbox.id={r.sandbox_id}"],
        capture_output=True, text=True,
    )  # fmt: skip
    assert rc.stdout.strip() == ""  # destroyed after the kill


async def test_exec_timeout_kills_sandbox_and_dead_is_normal(box: DockerSandbox) -> None:
    sid = await box.start(SandboxSpec(image=IMAGE, command=["sleep", "300"]))
    # Generous first-exec budget: under a long manifest run (R-002) the host is loaded and a cold
    # runsc exec can exceed 20 s. A timeout here would kill the sandbox, so warm it up wide.
    ok = await box.exec(sid, ["echo", "hi"], timeout=90)
    assert ok.stdout.strip() == "hi" and not ok.died and not ok.timed_out
    hung = await box.exec(sid, ["sleep", "60"], timeout=2)
    assert hung.timed_out
    after = await box.exec(sid, ["echo", "x"], timeout=5)
    assert after.died  # sandbox death is a result, not an exception
    await box.destroy(sid)


async def test_reaper_removes_expired_and_dead(box: DockerSandbox) -> None:
    live = await box.start(
        SandboxSpec(image=IMAGE, command=["sleep", "300"], limits=Limits(ttl_seconds=3600))
    )
    short = await box.start(
        SandboxSpec(image=IMAGE, command=["sleep", "300"], limits=Limits(ttl_seconds=1))
    )
    dead = await box.start(SandboxSpec(image=IMAGE, command=["true"]))
    time.sleep(3)

    def exists(sid: str) -> bool:
        out = subprocess.run(
            ["docker", "ps", "-aq", "--filter", f"label=bb.sandbox.id={sid}"],
            capture_output=True, text=True,
        )  # fmt: skip
        return bool(out.stdout.strip())

    res = await box.reap()
    assert len(res.containers) >= 2
    assert not exists(short) and not exists(dead) and exists(live)
    nets = subprocess.run(
        ["docker", "network", "ls", "-q", "--filter", f"label=bb.sandbox.id={short}"],
        capture_output=True, text=True,
    )  # fmt: skip
    assert nets.stdout.strip() == ""
    await box.destroy(live)


async def test_hostile_hook_cannot_read_host_env_or_secrets(
    box: DockerSandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SECRET_KEY", "host-secret-ZZZ-9f3")
    monkeypatch.setenv("BUILDER_DATABASE_URL", "postgresql://u:host-secret-ZZZ-9f3@h/db")
    r = await box.run(
        py(
            """
            import os, glob, json
            seen = {"env": dict(os.environ)}
            try:
                seen["pid1"] = open("/proc/1/environ").read()
            except OSError as e:
                seen["pid1"] = "denied"
            for p in ("/root", "/home", "/mnt", "/run/secrets", "/var/run/docker.sock", "/etc/shadow"):
                try:
                    seen[p] = os.listdir(p) if os.path.isdir(p) else open(p).read()
                except OSError:
                    seen[p] = "denied"
            print(json.dumps(seen))
            """
        )
    )
    assert "host-secret-ZZZ-9f3" not in r.stdout + r.stderr
    seen = json.loads(r.stdout)
    assert "SECRET_KEY" not in seen["env"] and "BUILDER_DATABASE_URL" not in seen["env"]
    assert seen["/var/run/docker.sock"] == "denied" and seen["/etc/shadow"] == "denied"
    assert not seen["/mnt"] and not seen["/home"]


async def test_cannot_join_another_sandboxs_or_unlabelled_network(box: DockerSandbox) -> None:
    from app.services.sandbox import SandboxError

    a_id, b_id = "a1" * 8, "b2" * 8
    net_a = await box.create_network(a_id)
    foreign = "bbtest-foreign-net"
    subprocess.run(
        ["docker", "network", "create", "--internal", foreign], check=True, capture_output=True
    )
    try:
        for net in (net_a, foreign):
            with pytest.raises(SandboxError):
                await box.start(
                    SandboxSpec(image=IMAGE, command=["true"], network=net, sandbox_id=b_id)
                )
        own = await box.start(
            SandboxSpec(image=IMAGE, command=["sleep", "30"], network=net_a, sandbox_id=a_id)
        )
        await box.destroy(own)
        with pytest.raises(SandboxError):  # image outside the allowlist is never pulled or run
            await box.start(SandboxSpec(image="alpine:latest", command=["true"], sandbox_id=b_id))
    finally:
        subprocess.run(["docker", "network", "rm", foreign], capture_output=True)
        subprocess.run(["docker", "network", "rm", net_a], capture_output=True)
