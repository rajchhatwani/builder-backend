"""Test support for regulated mode (generated): a throwaway 0600 key file with two keys."""

import base64
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.regulated import keys


def key_line(key_id: str, seed: int) -> str:
    return f"{key_id} {base64.urlsafe_b64encode(bytes([seed]) * 32).decode()}"


@pytest.fixture(autouse=True)
def regulated_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "regulated.keys"
    path.write_text(f"{key_line('k2', 2)}\n{key_line('k1', 1)}\n")
    path.chmod(0o600)
    monkeypatch.setenv("REGULATED_KEY_PROVIDER", "file")
    monkeypatch.setenv("REGULATED_KEY_FILE", str(path))
    keys.reset()
    yield path
    keys.reset()


def write_keys(path: Path, *lines: str) -> None:
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o600)
    keys.reset()

