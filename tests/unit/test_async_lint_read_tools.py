import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = ["app/services/agent/tools/read_tools.py"]


def test_read_tools_has_no_unjustified_async_lint() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "ruff", "check", *FILES, "--select", "ASYNC240"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout[-800:]
