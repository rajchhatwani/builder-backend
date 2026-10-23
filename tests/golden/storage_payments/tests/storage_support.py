"""Test support for the file module (generated).

The tests never talk to a real object store or a real scanner. `tests/fake_clamd.py` is a stand-in for
clamd that runs as a real TCP server (so the real scanner client is what is tested), and `MemoryBackend`
stands in for the bucket. Everything else (database, roles, routes, audit trail) is the real thing.
"""

import io
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any, BinaryIO

import pytest
from httpx import AsyncClient, Response

from app.auth import config as auth_config
from app.auth.service import effective_roles
from app.storage import clamav, config, sniff
from app.storage.backend import BackendUnavailable, ObjectMissing, set_backend
from tests._auth_support import ALL_ROLES, sign_in
from tests.fake_clamd import FakeClamd

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PDF = b"%PDF-1.7\n" + b"%" * 64
ZIP = b"PK\x03\x04" + b"\x00" * 64
EXE = b"MZ\x90\x00" + b"\x00" * 128
HTML = b"<!DOCTYPE html><html><body><script>alert(1)</script></body></html>"
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"></svg>'

# Tried in this order: the first one the project's allowed types accept is the "normal" test file.
SAMPLES: tuple[tuple[str, bytes, str], ...] = (
    ("note.txt", b"hello from the tests\n", "text/plain"),
    ("picture.png", PNG, "image/png"),
    ("document.pdf", PDF, "application/pdf"),
    ("photo.jpg", JPEG, "image/jpeg"),
    ("archive.zip", ZIP, "application/zip"),
    ("data.csv", b"id,name\n1,Ann\n", "text/csv"),
)


class MemoryBackend:
    """An in-memory bucket with switches for the ways a real one fails."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []
        self.fail_put = False
        self.fail_get = False
        self.fail_delete = False

    async def put(self, key: str, file: BinaryIO, *, sha256: str) -> None:
        if self.fail_put:
            raise BackendUnavailable("down")
        file.seek(0)
        self.objects[key] = file.read()

    async def stream(self, key: str) -> AsyncIterator[bytes]:
        if self.fail_get:
            raise BackendUnavailable("down")
        if key not in self.objects:
            raise ObjectMissing("missing")
        data = self.objects[key]
        for start in range(0, len(data), 7000):
            yield data[start : start + 7000]

    async def delete(self, key: str) -> None:
        if self.fail_delete:
            raise BackendUnavailable("down")
        self.objects.pop(key, None)
        self.deleted.append(key)

    async def exists(self, key: str) -> bool:
        return key in self.objects

    def presign(self, key: str, *, filename_header: str, ttl: int) -> str:
        return f"https://objects.test/{key}?ttl={ttl}"

    async def check(self) -> None:
        if self.fail_get:
            raise BackendUnavailable("down")

    async def ensure_bucket(self) -> None:
        return None


@pytest.fixture(scope="session")
def fake_clamd_server() -> Iterator[FakeClamd]:
    server = FakeClamd().start()
    yield server
    server.stop()


@pytest.fixture
def fake_clamd(fake_clamd_server: FakeClamd) -> Iterator[FakeClamd]:
    fake_clamd_server.reset()
    yield fake_clamd_server


@pytest.fixture
def storage_env(
    monkeypatch: pytest.MonkeyPatch, fake_clamd: FakeClamd, outbox: object
) -> Iterator[MemoryBackend]:
    """The scanner stand-in, an in-memory bucket and fresh settings for every test."""
    for name in (
        "STORAGE_ENDPOINT_URL",
        "STORAGE_PUBLIC_ENDPOINT_URL",
        "STORAGE_ACCESS_KEY_ID",
        "STORAGE_SECRET_ACCESS_KEY",
        "STORAGE_ACCESS_KEY_ID_FILE",
        "STORAGE_SECRET_ACCESS_KEY_FILE",
        "STORAGE_CREATE_BUCKET",
        "STORAGE_TRUSTED_PROXIES",
        "APP_ENV",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLAMD_HOST", "127.0.0.1")
    monkeypatch.setenv("CLAMD_PORT", str(fake_clamd.port))
    monkeypatch.setenv("STORAGE_SCAN_TIMEOUT_SECONDS", "5")
    config.get_storage_settings.cache_clear()
    clamav.reset_version_cache()
    backend = MemoryBackend()
    set_backend(backend)
    yield backend
    set_backend(None)
    config.get_storage_settings.cache_clear()
    clamav.reset_version_cache()


def sample_file() -> tuple[str, bytes, str]:
    """A file this project accepts, different every time. Skips when the project's allowed types
    are ones the tests have no sample for."""
    for name, data, content_type in SAMPLES:
        if sniff.type_allowed(config.ALLOWED_TYPES, sniff.detect(data), content_type):
            return name, data + uuid.uuid4().hex.encode(), content_type
    pytest.skip("this project's allowed file types have no sample in the tests")


async def upload(
    client: AsyncClient,
    *,
    name: str | None = None,
    data: bytes | None = None,
    content_type: str | None = None,
    shared: bool = False,
) -> Response:
    sample_name, sample_data, sample_type = sample_file() if data is None else ("f.bin", b"", "")
    body = sample_data if data is None else data
    files = {
        "file": (
            name or sample_name,
            io.BytesIO(body),
            content_type or sample_type or "application/octet-stream",
        )
    }
    return await client.post("/files", files=files, data={"shared": "true"} if shared else None)


async def upload_ok(client: AsyncClient, **kwargs: Any) -> dict[str, Any]:
    response = await upload(client, **kwargs)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def can(role: str, key: str) -> bool:
    """Whether a user holding `role` (plus the default roles) may do `key` in this project."""
    held = effective_roles([role, *auth_config.DEFAULT_ROLES])
    return bool(held & set(config.ROLES.get(key, ())))


def pick_role(*has: str, lacks: tuple[str, ...] = ()) -> str:
    """A role that may do everything in `has` and nothing in `lacks`; skips if the project has none."""
    for role in ALL_ROLES:
        if all(can(role, key) for key in has) and not any(can(role, key) for key in lacks):
            return role
    pytest.skip(f"no role may {', '.join(has)} without being able to {', '.join(lacks) or 'nothing'}")


async def user(
    client: AsyncClient, email: str, role: str, *, n: int = 0, join: str | None = None
) -> dict[str, str]:
    """The Authorization header of a user who holds `role`."""
    return await sign_in(client, email, roles=[role], n=n, join=join)
