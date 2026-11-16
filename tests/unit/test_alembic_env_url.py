"""AUDIT F-0138: alembic/env.py must accept a %-encoded password in the database URL."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_env_py_accepts_percent_encoded_password() -> None:
    env = {
        **os.environ,
        "BUILDER_DATABASE_URL": "postgresql+asyncpg://u:p%40ss@localhost/db",
        "SECRET_KEY": "env-url-test-secret",
    }
    done = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "invalid interpolation" not in done.stderr, done.stderr[-400:]
    assert done.returncode == 0, done.stderr[-400:]
