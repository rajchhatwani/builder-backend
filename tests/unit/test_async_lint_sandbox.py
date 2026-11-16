import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = ["app/services/sandbox/base.py", "app/services/sandbox/docker.py", "app/services/sandbox/remote.py"]


def test_sandbox_services_have_no_unjustified_async_lint() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "ruff", "check", *FILES, "--select", "ASYNC109"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout[-800:]
