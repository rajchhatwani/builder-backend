"""P1: a real sandbox (docker + runsc) driven through RemoteSandbox -> in-process runner."""

import shutil
import subprocess
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.services.sandbox import DockerSandbox, RemoteSandbox, SandboxError, SandboxSpec
from app.services.sandbox.runner import RunnerCore, create_app

TOKEN = "e2e-" + "r" * 40


def _have_runsc() -> bool:
    if shutil.which("docker") is None:
        return False
    out = subprocess.run(["docker", "info", "--format", "{{json .Runtimes}}"], capture_output=True, text=True)
    return out.returncode == 0 and "runsc" in out.stdout


pytestmark = pytest.mark.skipif(not _have_runsc(), reason="needs docker with the runsc runtime")


@pytest.fixture
async def rig(tmp_path: Path) -> AsyncIterator[tuple[RemoteSandbox, Path]]:
    root = tmp_path / "mounts"
    (root / "proj").mkdir(parents=True)
    (root / "proj" / "hello.txt").write_text("from-mount")
    rs = Settings(environment="test", sandbox_runtime="runsc", runner_mount_root=str(root))
    app = create_app(rs, token=TOKEN, core=RunnerCore(rs))
    api = Settings(environment="test", sandbox_runner_url="http://127.0.0.1:8790", sandbox_runner_token=TOKEN)  # type: ignore[arg-type]
    yield RemoteSandbox(api, transport=httpx.ASGITransport(app=app)), root
    await DockerSandbox(rs).reap(now=time.time() + 10**7)


async def test_real_sandbox_through_the_runner(rig: tuple[RemoteSandbox, Path]) -> None:
    box, root = rig
    await box.check_runtime()
    r = await box.run(SandboxSpec(
        image="python:3.12-slim", code_dir=root / "proj",
        command=["python", "-c", "print(open('/workspace/hello.txt').read()); import socket\n"
                 "s=socket.socket(); s.settimeout(2)\n"
                 "try: s.connect(('169.254.169.254',80)); print('CONNECTED')\n"
                 "except OSError: print('BLOCKED')"],
    ))
    assert r.exit_code == 0 and "from-mount" in r.stdout and "BLOCKED" in r.stdout, (r.stdout, r.stderr)
    # a mount outside the root and an unlisted image never reach docker
    with pytest.raises(SandboxError):
        await box.run(SandboxSpec(image="python:3.12-slim", code_dir=Path("/etc")))
    with pytest.raises(SandboxError):
        await box.run(SandboxSpec(image="alpine:latest"))
