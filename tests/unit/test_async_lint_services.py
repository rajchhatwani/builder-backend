import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = [
    "app/services/preview_runtime.py",
    "app/services/preview_service.py",
    "app/services/workspace_files.py",
    "app/services/workspace_service.py",
]


def test_services_have_no_unjustified_async_lint() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "ruff", "check", *FILES, "--select", "ASYNC109,ASYNC240"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout[-800:]
