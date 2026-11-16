import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_validation_seed_has_no_unused_loop_variables() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "app/core/validation_seed.py", "--select", "B007"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout[-500:]
