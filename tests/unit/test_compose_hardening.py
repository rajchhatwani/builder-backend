"""Audit B1-036: compose skips the dev group and publishes ports on loopback only."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = (ROOT / "docker-compose.yml").read_text()
DOCKERFILE = (ROOT / "Dockerfile").read_text()


def test_image_env_disables_dev_group_for_uv_run() -> None:
    assert re.search(r"UV_NO_DEV=1", DOCKERFILE)


def test_published_ports_bind_loopback() -> None:
    ports = re.findall(r'^\s*-\s*"(\d+:\d+)"\s*$', COMPOSE, re.M)
    assert ports == []
    published = re.findall(r'^\s*-\s*"(127\.0\.0\.1:\d+:\d+)"\s*$', COMPOSE, re.M)
    assert len(published) == 3
