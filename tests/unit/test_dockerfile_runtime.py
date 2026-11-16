"""Audit B1-002: the shipped image must start without re-syncing deps and carry what it shells out to."""

from pathlib import Path

DOCKERFILE = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text()


def _cmd_line() -> str:
    return next(line for line in DOCKERFILE.splitlines() if line.startswith("CMD "))


def test_cmd_does_not_resync_dependencies() -> None:
    cmd = _cmd_line()
    assert '"uv", "run"' not in cmd or ("--no-sync" in cmd or "--frozen" in cmd and "--no-dev" in cmd)
    assert "/app/.venv/bin/uvicorn" in cmd


def test_image_ships_scripts_and_git() -> None:
    assert "COPY scripts ./scripts" in DOCKERFILE
    assert " git" in DOCKERFILE and "apt-get install" in DOCKERFILE
