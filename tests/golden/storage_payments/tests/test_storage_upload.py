"""File API tests (generated): upload, list, download, delete, sharing and the file field.

They run the real routes, the real scanner client (against tests/fake_clamd.py), the real database
and an in-memory bucket. Nothing here talks to the internet.
"""

import hashlib
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from app.db import session_factory
from app.storage import config, maintenance, refs
from app.storage.models import StorAuditLog, StorFile
from tests import _factories
from tests._auth_support import ALL_ROLES, client_for, sign_in
from tests.storage_support import (
    MemoryBackend,
    pick_role,
    sample_file,
    upload,
    upload_ok,
    user,
)

pytestmark = pytest.mark.usefixtures("storage_env")
proxy_only = pytest.mark.skipif(
    config.DOWNLOAD_MODE != "proxy", reason="this project hands out presigned links instead"
)


async def file_row(file_id: str) -> StorFile:
    async with session_factory() as session:
        row = await session.get(StorFile, uuid.UUID(file_id))
        assert row is not None
        return row


_started = datetime.now(UTC)


@pytest.fixture(autouse=True)
def _audit_window() -> None:
    """The audit table is append-only and never emptied, so each test looks only at its own rows."""
    global _started
    _started = datetime.now(UTC)


async def audit_events(file_id: str | None = None, event: str | None = None) -> list[StorAuditLog]:
    async with session_factory() as session:
        query = (
            sa.select(StorAuditLog)
            .where(StorAuditLog.at >= _started)
            .order_by(StorAuditLog.at, StorAuditLog.seq)
        )
        if file_id is not None:
            query = query.where(StorAuditLog.file_id == uuid.UUID(file_id))
        if event is not None:
            query = query.where(StorAuditLog.event == event)
        return list((await session.execute(query)).scalars())


@pytest.fixture
async def alice(client: AsyncClient) -> AsyncClient:
    """A signed-in user who can upload and read files."""
    headers = await user(client, "alice@example.com", pick_role("upload", "read"))
    async with client_for(headers) as http:
        yield http  # type: ignore[misc]


async def test_upload_list_get_and_download_round_trip(
    alice: AsyncClient, storage_env: MemoryBackend
) -> None:
    name, data, content_type = sample_file()
    created = await upload_ok(alice, name=name, data=data, content_type=content_type)
    assert created["status"] == "clean"
    assert created["size_bytes"] == len(data)
    assert created["sha256"] == hashlib.sha256(data).hexdigest()
    assert created["original_name"] == name
    assert created["scanned_at"] is not None
    file_id = created["id"]

    assert (await alice.get(f"/files/{file_id}")).json()["id"] == file_id
    listing = (await alice.get("/files")).json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == file_id
    assert (await alice.get("/files", params={"mine": "true"})).json()["total"] == 1

    row = await file_row(file_id)
    assert row.status == "clean" and (row.scan_engine or "").startswith("ClamAV")
    assert storage_env.objects[row.storage_key] == data

    response = await alice.get(f"/files/{file_id}/download", follow_redirects=False)
    if config.DOWNLOAD_MODE == "presigned":
        assert response.status_code == 307
        assert response.headers["location"].startswith("https://objects.test/")
        assert "ttl=60" in response.headers["location"]
    else:
        assert response.status_code == 200
        assert response.content == data
        assert response.headers["content-length"] == str(len(data))

    events = [e.event for e in await audit_events(file_id)]
    assert events == ["upload.accepted", "download.granted"]


async def test_the_scanner_saw_exactly_the_uploaded_bytes(alice: AsyncClient, fake_clamd: Any) -> None:
    _, data, content_type = sample_file()
    await upload_ok(alice, name="a.bin", data=data, content_type=content_type)
    assert fake_clamd.scanned == [data]
    assert fake_clamd.framing_errors == 0


async def test_an_empty_file_is_refused(alice: AsyncClient, storage_env: MemoryBackend) -> None:
    response = await upload(alice, name="empty.txt", data=b"", content_type="text/plain")
    assert response.status_code == 422
    assert response.json()["code"] == "empty_file"
    assert storage_env.objects == {}


async def test_exactly_one_file_part_is_required(alice: AsyncClient) -> None:
    none = await alice.post("/files", data={"shared": "false"})
    assert none.status_code == 422 and none.json()["code"] == "file_required"
    wrong_name = await alice.post("/files", files={"document": ("a.txt", b"hi", "text/plain")})
    assert wrong_name.status_code == 422 and wrong_name.json()["code"] == "file_required"
    two = await alice.post(
        "/files", files=[("file", ("a.txt", b"one", "text/plain")), ("file", ("b.txt", b"two", "text/plain"))]
    )
    assert two.status_code in (400, 422)


async def test_the_shared_flag_must_be_true_or_false(alice: AsyncClient) -> None:
    _, data, content_type = sample_file()
    response = await alice.post(
        "/files", files={"file": ("a", data, content_type)}, data={"shared": "maybe"}
    )
    assert response.status_code == 422


async def test_anonymous_callers_are_refused_everywhere(client: AsyncClient) -> None:
    some_id = uuid.uuid4()
    calls = [
        client.post("/files", files={"file": ("a.txt", b"hi", "text/plain")}),
        client.get("/files"),
        client.get("/files/status"),
        client.get(f"/files/{some_id}"),
        client.get(f"/files/{some_id}/download"),
        client.delete(f"/files/{some_id}"),
        client.get(f"/files/{some_id}/audit"),
        client.post(f"/files/{some_id}/quarantine"),
        client.post(f"/files/{some_id}/release"),
    ]
    for call in calls:
        assert (await call).status_code == 401


async def test_an_unknown_file_is_not_found(alice: AsyncClient) -> None:
    missing = uuid.uuid4()
    for path in (f"/files/{missing}", f"/files/{missing}/download"):
        response = await alice.get(path)
        assert response.status_code == 404 and response.json()["code"] == "not_found"
    assert (await alice.delete(f"/files/{missing}")).status_code == 404
    assert (await alice.get("/files/not-a-uuid")).status_code == 422


@proxy_only
async def test_an_object_that_vanished_from_the_bucket_is_a_clean_error(
    alice: AsyncClient, storage_env: MemoryBackend
) -> None:
    created = await upload_ok(alice)
    storage_env.objects.clear()
    response = await alice.get(f"/files/{created['id']}/download")
    assert response.status_code == 503 and response.json()["code"] == "storage_unavailable"
    assert [e.event for e in await audit_events(created["id"], "download.failed")] == ["download.failed"]


async def test_presigned_mode_redirects_and_never_streams(
    alice: AsyncClient, monkeypatch: pytest.MonkeyPatch, storage_env: MemoryBackend
) -> None:
    monkeypatch.setattr(config, "DOWNLOAD_MODE", "presigned")
    created = await upload_ok(alice)
    response = await alice.get(f"/files/{created['id']}/download", follow_redirects=False)
    assert response.status_code == 307
    row = await file_row(created["id"])
    assert response.headers["location"] == f"https://objects.test/{row.storage_key}?ttl=60"
    assert response.headers["cache-control"] == "no-store"


async def test_shared_files_can_be_read_by_other_readers(client: AsyncClient) -> None:
    sharer = pick_role("upload", "share", "read")
    reader = pick_role("read", lacks=("read_all",))
    owner_headers = await user(client, "owner@example.com", sharer)
    reader_headers = await user(client, "reader@example.com", reader, n=1, join="owner@example.com")
    async with client_for(owner_headers) as owner, client_for(reader_headers) as other:
        private = await upload_ok(owner)
        shared = await upload_ok(owner, shared=True)
        assert shared["shared"] is True
        assert (await other.get(f"/files/{shared['id']}")).status_code == 200
        assert (await other.get(f"/files/{private['id']}")).status_code == 404
        ids = {item["id"] for item in (await other.get("/files")).json()["items"]}
        assert ids == {shared["id"]}


async def test_delete_erases_the_object_and_keeps_only_a_tombstone(
    client: AsyncClient, storage_env: MemoryBackend
) -> None:
    role = pick_role("upload", "read", "delete")
    async with client_for(await user(client, "eraser@example.com", role)) as http:
        created = await upload_ok(http, name="secret-plan.txt")
        key = (await file_row(created["id"])).storage_key
        assert key in storage_env.objects
        assert (await http.delete(f"/files/{created['id']}")).status_code == 204
        assert key not in storage_env.objects
        assert (await http.get(f"/files/{created['id']}")).status_code == 404
        assert (await http.delete(f"/files/{created['id']}")).status_code == 404
        assert (await http.get("/files")).json()["total"] == 0

    row = await file_row(created["id"])
    assert row.status == "deleted" and row.original_name is None and row.deleted_at is not None
    assert row.sha256 == created["sha256"]  # the tombstone keeps the hash, for the record
    events = await audit_events(created["id"], "file.deleted")
    assert len(events) == 1 and "secret-plan" not in str(events[0].data)


async def test_a_failed_delete_is_retried_by_the_maintenance_command(
    client: AsyncClient, storage_env: MemoryBackend
) -> None:
    role = pick_role("upload", "read", "delete")
    async with client_for(await user(client, "retry@example.com", role)) as http:
        created = await upload_ok(http)
        storage_env.fail_delete = True
        response = await http.delete(f"/files/{created['id']}")
        assert response.status_code == 503 and response.json()["code"] == "storage_unavailable"
        assert (await file_row(created["id"])).status == "deleting"
        assert (await http.get(f"/files/{created['id']}")).status_code == 404  # already hidden

        storage_env.fail_delete = False
        async with session_factory() as session:  # the retry waits a few minutes before it picks it up
            await session.execute(
                sa.text("UPDATE stor_files SET updated_at = now() - interval '1 hour' WHERE id = :id"),
                {"id": uuid.UUID(created["id"])},
            )
            await session.commit()
        assert await maintenance.finish_deletes() == 1
    assert (await file_row(created["id"])).status == "deleted"
    assert (await file_row(created["id"])).storage_key not in storage_env.objects


async def test_a_file_that_a_record_uses_cannot_be_deleted(client: AsyncClient) -> None:
    if not refs.FILE_REFERENCES:
        pytest.skip("this project has no entity with a file field")
    table, column = refs.FILE_REFERENCES[0]
    make = getattr(_factories, f"make_{table}", None)
    if make is None:
        pytest.skip(f"{table} cannot be created through the API")
    # Someone who holds every role can create the record and erase the file.
    headers = await sign_in(client, "everything@example.com", roles=list(ALL_ROLES))
    async with client_for(headers) as http:
        file_id = (await upload_ok(http))["id"]
        record = await make(http, **{column: file_id})
        assert record[column] == file_id
        blocked = await http.delete(f"/files/{file_id}")
        assert blocked.status_code == 409 and blocked.json()["code"] == "file_in_use"
        assert (await file_row(file_id)).status == "clean"  # nothing was erased
        assert re.fullmatch(r"[0-9a-f]{64}", (await http.get(f"/files/{file_id}")).json()["sha256"])
