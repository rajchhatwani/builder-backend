import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_behavior_routes_bind_loop_variables() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "app/api/behavior.py", "--select", "B023"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout[-500:]
