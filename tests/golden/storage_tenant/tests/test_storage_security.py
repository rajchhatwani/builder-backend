"""Security tests of the file module (generated). The test names are the ones listed in
docs/storage-security.md, so a reviewer can map each threat to the check that covers it."""

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.exc import DBAPIError

from app.auth.models import AuthUser
from app.core import redact
from app.core.errors import AppError
from app.db import engine, session_factory
from app.storage import config, maintenance, refs, service, sniff
from app.storage.models import StorAuditLog, StorFile
from tests._auth_support import client_for
from tests.fake_clamd import MARKER, SIGNATURE, FakeClamd
from tests.storage_support import (
    EXE,
    HTML,
    PNG,
    SVG,
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


async def rows() -> list[StorFile]:
    async with session_factory() as session:
        return list((await session.execute(sa.select(StorFile))).scalars())


_started = datetime.now(UTC)


@pytest.fixture(autouse=True)
def _audit_window() -> None:
    """The audit table is append-only and never emptied, so each test looks only at its own rows."""
    global _started
    _started = datetime.now(UTC)


async def events(event: str | None = None, file_id: str | None = None) -> list[StorAuditLog]:
    async with session_factory() as session:
        query = (
            sa.select(StorAuditLog)
            .where(StorAuditLog.at >= _started)
            .order_by(StorAuditLog.at, StorAuditLog.seq)
        )
        if event is not None:
            query = query.where(StorAuditLog.event == event)
        if file_id is not None:
            query = query.where(StorAuditLog.file_id == uuid.UUID(file_id))
        return list((await session.execute(query)).scalars())


@pytest.fixture
async def alice(client: AsyncClient) -> AsyncClient:
    headers = await user(client, "alice@example.com", pick_role("upload", "read"))
    async with client_for(headers) as http:
        yield http  # type: ignore[misc]


# --- 1. malware ---------------------------------------------------------------------------------


async def test_malware_is_rejected_and_never_stored(
    alice: AsyncClient, storage_env: MemoryBackend
) -> None:
    name, data, content_type = sample_file()
    response = await upload(alice, name="invoice.pdf", data=data + MARKER, content_type=content_type)
    assert response.status_code == 422
    assert response.json()["code"] == "malware_detected"
    assert SIGNATURE not in response.text  # the signature name helps attackers tune evasion
    assert storage_env.objects == {}
    assert await rows() == []
    (entry,) = await events("upload.rejected")
    assert entry.outcome == "rejected" and entry.data["reason"] == "malware_detected"
    assert entry.data["detection"] == SIGNATURE
    assert "invoice" not in json.dumps(entry.data)  # the audit trail never holds file names


@pytest.mark.parametrize("failure", ["error", "garbage", "unknown", "close", "unreachable"])
async def test_scanner_down_refuses_the_upload(
    alice: AsyncClient,
    storage_env: MemoryBackend,
    fake_clamd: FakeClamd,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    if failure == "unreachable":
        monkeypatch.setenv("CLAMD_PORT", "1")
        config.get_storage_settings.cache_clear()
    else:
        fake_clamd.mode = failure
    response = await upload(alice)
    assert response.status_code == 503
    assert response.json()["code"] == "scanner_unavailable"
    assert storage_env.objects == {} and await rows() == []  # never stored, never "assumed clean"
    (entry,) = await events("upload.rejected")
    assert entry.outcome == "error" and entry.data["reason"] == "scanner_unavailable"


async def test_the_bucket_being_down_leaves_nothing_behind(
    alice: AsyncClient, storage_env: MemoryBackend
) -> None:
    storage_env.fail_put = True
    response = await upload(alice)
    assert response.status_code == 503 and response.json()["code"] == "storage_unavailable"
    assert await rows() == []
    storage_env.fail_put = False
    assert (await upload(alice)).status_code == 201  # and it recovers by itself


async def test_rescan_quarantines_a_file_that_is_no_longer_clean(
    client: AsyncClient, storage_env: MemoryBackend
) -> None:
    operator = pick_role("upload", "read", "operate")
    async with client_for(await user(client, "operator@example.com", operator)) as http:
        created = await upload_ok(http)
        row = (await rows())[0]
        # Pretend the signatures learned about this file since it was uploaded.
        infected = storage_env.objects[row.storage_key] + MARKER
        storage_env.objects[row.storage_key] = infected
        async with session_factory() as session:
            stored = await session.get(StorFile, row.id)
            assert stored is not None
            stored.sha256 = hashlib.sha256(infected).hexdigest()
            stored.size_bytes = len(infected)
            stored.scanned_at = None
            await session.commit()
            verdict = await service.rescan(session, stored, actor_id=None, info=service.RequestInfo())
        assert verdict == "infected"
        assert (await rows())[0].status == "quarantined"
        blocked = await http.get(f"/files/{created['id']}/download")
        assert blocked.status_code == 409 and blocked.json()["code"] == "file_unavailable"
        (entry,) = await events("file.rescanned")
        assert entry.outcome == "error" and entry.data["verdict"] == "infected"
        await_denied = await events("download.denied")
        assert len(await_denied) == 1 and await_denied[0].outcome == "denied"


async def test_a_quarantined_file_can_be_released_only_after_a_clean_rescan(
    client: AsyncClient, storage_env: MemoryBackend
) -> None:
    operator = pick_role("upload", "read", "operate")
    async with client_for(await user(client, "operator@example.com", operator)) as http:
        created = await upload_ok(http)
        file_id = created["id"]
        assert (await http.post(f"/files/{file_id}/quarantine", json={"reason": "suspicious"})).status_code == 200
        assert (await http.get(f"/files/{file_id}/download")).status_code == 409
        released = await http.post(f"/files/{file_id}/release")
        assert released.status_code == 200 and released.json()["status"] == "clean"
        assert (await http.post(f"/files/{file_id}/release")).status_code == 409  # not quarantined now
        # Now make the stored bytes infected: the release must be refused.
        await http.post(f"/files/{file_id}/quarantine")
        row = (await rows())[0]
        storage_env.objects[row.storage_key] = storage_env.objects[row.storage_key] + MARKER
        refused = await http.post(f"/files/{file_id}/release")
        assert refused.status_code == 409 and refused.json()["code"] == "release_refused"
        assert (await rows())[0].status == "quarantined"


async def test_scanner_and_bucket_health_is_visible_to_operators_only(
    client: AsyncClient, fake_clamd: FakeClamd, storage_env: MemoryBackend
) -> None:
    operator = pick_role("operate")
    async with client_for(await user(client, "ops@example.com", operator)) as http:
        status = (await http.get("/files/status")).json()
        assert status["scanner"]["ok"] is True and status["scanner"]["engine"].startswith("ClamAV")
        assert status["bucket"]["ok"] is True
        assert status["max_file_bytes"] == config.MAX_FILE_BYTES
        storage_env.fail_get = True
        assert (await http.get("/files/status")).json()["bucket"]["ok"] is False
    outsider = pick_role("upload", lacks=("operate",))
    async with client_for(await user(client, "plain@example.com", outsider, n=1)) as http:
        assert (await http.get("/files/status")).status_code == 403


# --- 2. what a file really is ---------------------------------------------------------------------


async def test_renamed_executable_is_not_an_image(alice: AsyncClient) -> None:
    response = await upload(alice, name="holiday.png", data=EXE, content_type="image/png")
    if config.ALLOWED_TYPES and not sniff.type_allowed(
        config.ALLOWED_TYPES, sniff.detect(EXE), "image/png"
    ):
        assert response.status_code == 415
        assert response.json()["code"] == "type_not_allowed"
        assert await rows() == []
        (entry,) = await events("upload.rejected")
        assert entry.data["detected_type"] == "application/vnd.microsoft.portable-executable"
    else:  # any type is allowed here: it is stored as what it is, not as what it claims to be
        assert response.status_code == 201, response.text
        assert response.json()["content_type"] == "application/vnd.microsoft.portable-executable"


async def test_declared_type_is_not_trusted(alice: AsyncClient) -> None:
    _, data, _ = sample_file()
    response = await upload(alice, name="page.html", data=data, content_type="text/html")
    assert response.status_code == 201, response.text
    assert response.json()["content_type"] == sniff.detect(data).mime
    assert (await rows())[0].declared_type == "text/html"  # recorded as a claim, nothing more


# --- 3. serving files safely --------------------------------------------------------------------


@proxy_only
async def test_download_headers_are_safe(alice: AsyncClient) -> None:
    created = await upload_ok(alice, name='evil"\r\nX-Injected: yes.txt')
    response = await alice.get(f"/files/{created['id']}/download")
    assert response.status_code == 200
    # The headers the service itself sets (other middleware may add the same ones as well).
    assert service.SAFETY_HEADERS == {
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cache-Control": "private, no-store",
    }
    headers = response.headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert headers["cache-control"] == "private, no-store"
    assert headers["content-disposition"].startswith("attachment;")
    assert "x-injected" not in headers
    assert headers["content-type"] in ("application/octet-stream", "image/png", "image/jpeg", "image/gif", "image/webp")


@proxy_only
async def test_html_and_svg_are_never_served_inline(alice: AsyncClient) -> None:
    served = 0
    for data, mime in ((HTML, "text/html"), (SVG, "image/svg+xml")):
        if not sniff.type_allowed(config.ALLOWED_TYPES, sniff.detect(data), mime):
            continue
        created = await upload_ok(alice, name="page.html", data=data, content_type=mime)
        response = await alice.get(f"/files/{created['id']}/download", params={"inline": "true"})
        assert response.status_code == 200
        assert response.headers["content-disposition"].startswith("attachment;")
        assert response.headers["content-type"] == "application/octet-stream"
        served += 1
    if not served:
        pytest.skip("this project's allowed types exclude HTML and SVG, so they cannot be uploaded")


@proxy_only
async def test_plain_images_are_inline_only_when_the_project_allows_it(
    alice: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not sniff.type_allowed(config.ALLOWED_TYPES, sniff.detect(PNG), "image/png"):
        pytest.skip("images are not allowed in this project")
    created = await upload_ok(alice, name="pic.png", data=PNG, content_type="image/png")
    url = f"/files/{created['id']}/download"
    monkeypatch.setattr(config, "ALLOW_INLINE_IMAGES", False)
    assert (await alice.get(url, params={"inline": "true"})).headers["content-disposition"].startswith("attachment;")
    monkeypatch.setattr(config, "ALLOW_INLINE_IMAGES", True)
    inline = await alice.get(url, params={"inline": "true"})
    assert inline.headers["content-disposition"].startswith("inline;")
    assert inline.headers["content-type"] == "image/png"
    assert (await alice.get(url)).headers["content-disposition"].startswith("attachment;")


# --- 4. names and keys --------------------------------------------------------------------------


async def test_filenames_are_sanitised_and_never_decide_the_key(
    alice: AsyncClient, storage_env: MemoryBackend
) -> None:
    created = await upload_ok(alice, name="../../../etc/passwd‮.txt")
    assert created["original_name"] == "passwd.txt"
    (key,) = storage_env.objects
    assert "passwd" not in key and ".." not in key and "etc" not in key
    pattern = rf"{re.escape(config.KEY_PREFIX)}/(_|[0-9a-f-]{{36}})/\d{{4}}/\d{{2}}/[0-9a-f-]{{36}}"
    assert re.fullmatch(pattern, key), key


async def test_storage_keys_are_random(alice: AsyncClient, storage_env: MemoryBackend) -> None:
    _, data, content_type = sample_file()
    for _ in range(2):
        await upload_ok(alice, name="same.txt", data=data, content_type=content_type)
    assert len(storage_env.objects) == 2  # the same bytes under the same name still get two keys


# --- 5. flooding --------------------------------------------------------------------------------


async def test_oversize_body_is_refused_early(
    alice: AsyncClient, storage_env: MemoryBackend, fake_clamd: FakeClamd
) -> None:
    if config.MAX_FILE_BYTES > 64 * 1024 * 1024:
        pytest.skip("the limit is too large to exercise with a real body in a unit test")
    big = b"x" * (config.MAX_FILE_BYTES + 512 * 1024)
    response = await upload(alice, name="big.txt", data=big, content_type="text/plain")
    assert response.status_code == 413
    assert response.json()["code"] == "file_too_large"
    assert storage_env.objects == {} and fake_clamd.scanned == []  # stopped before any work


async def test_rate_limit(
    alice: AsyncClient, monkeypatch: pytest.MonkeyPatch, storage_env: MemoryBackend
) -> None:
    monkeypatch.setattr(config, "UPLOADS_PER_HOUR", 2)
    assert (await upload(alice)).status_code == 201
    _, data, content_type = sample_file()
    assert (await upload(alice, data=data + MARKER, content_type=content_type)).status_code == 422
    limited = await upload(alice)  # attempts count, accepted or not
    assert limited.status_code == 429 and limited.json()["code"] == "rate_limited"
    assert len(storage_env.objects) == 1
    assert len(await events("upload.rate_limited")) == 1


async def test_quota(alice: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _, data, content_type = sample_file()
    monkeypatch.setattr(config, "USER_QUOTA_BYTES", len(data) + 10)
    assert (await upload(alice, data=data, content_type=content_type)).status_code == 201
    second = await upload(alice, data=data, content_type=content_type)
    assert second.status_code == 422 and second.json()["code"] == "quota_exceeded"


# --- 6. who can see and do what -------------------------------------------------------------------


async def test_users_cannot_see_each_others_files(client: AsyncClient) -> None:
    role = pick_role("upload", "read", lacks=("read_all", "delete_all"))
    a = await user(client, "a@example.com", role)
    b = await user(client, "b@example.com", role, n=1, join="a@example.com")
    async with client_for(a) as first, client_for(b) as second:
        mine = await upload_ok(first)
        theirs = await upload_ok(second)
        for call in (
            second.get(f"/files/{mine['id']}"),
            second.get(f"/files/{mine['id']}/download"),
            second.delete(f"/files/{mine['id']}"),
        ):
            response = await call
            assert response.status_code == 404 and response.json()["code"] == "not_found"
        assert {i["id"] for i in (await second.get("/files")).json()["items"]} == {theirs["id"]}
        assert {i["id"] for i in (await first.get("/files")).json()["items"]} == {mine["id"]}


async def test_other_tenant_cannot_see_files(client: AsyncClient) -> None:
    if not config.MULTI_TENANT:
        pytest.skip("this project is not multi-tenant")
    role = pick_role("upload", "read", "read_all")
    a = await user(client, "a@example.com", role)
    b = await user(client, "b@example.com", role, n=1)  # no join: a tenant of their own
    async with client_for(a) as first, client_for(b) as second:
        mine = await upload_ok(first)
        assert (await second.get(f"/files/{mine['id']}")).status_code == 404
        assert (await second.get(f"/files/{mine['id']}/download")).status_code == 404
        assert (await second.get("/files")).json()["total"] == 0


async def test_only_allowed_roles_can_act(client: AsyncClient) -> None:
    nobody = pick_role(lacks=("upload", "read", "read_all", "operate", "delete", "delete_all"))
    async with client_for(await user(client, "nobody@example.com", nobody)) as http:
        denied = await upload(http)
        assert denied.status_code == 403 and denied.json()["code"] == "forbidden"
        assert (await http.get("/files")).status_code == 403
        assert (await http.get(f"/files/{uuid.uuid4()}")).status_code == 403
    assert [e.outcome for e in await events("upload.denied")] == ["denied"]
    assert await rows() == []


async def test_sharing_needs_its_own_role(client: AsyncClient) -> None:
    role = pick_role("upload", lacks=("share",))
    async with client_for(await user(client, "sharer@example.com", role)) as http:
        denied = await upload(http, shared=True)
        assert denied.status_code == 403
        assert (await upload(http)).status_code == 201


async def test_delete_needs_the_delete_role(client: AsyncClient) -> None:
    role = pick_role("upload", "read", lacks=("delete", "delete_all"))
    async with client_for(await user(client, "keeper@example.com", role)) as http:
        created = await upload_ok(http)
        denied = await http.delete(f"/files/{created['id']}")
        assert denied.status_code == 403
        assert (await http.get(f"/files/{created['id']}")).status_code == 200
    assert [e.outcome for e in await events("delete.denied")] == ["denied"]


async def test_only_operators_see_the_audit_trail(client: AsyncClient) -> None:
    role = pick_role("upload", "read", lacks=("operate",))
    async with client_for(await user(client, "worker@example.com", role)) as http:
        created = await upload_ok(http)
        assert (await http.get(f"/files/{created['id']}/audit")).status_code == 403
        assert (await http.post(f"/files/{created['id']}/quarantine")).status_code == 403
        assert (await http.post(f"/files/{created['id']}/release")).status_code == 403


# --- 7. file fields -------------------------------------------------------------------------------


async def test_file_field_rejects_foreign_and_missing_files(client: AsyncClient) -> None:
    role = pick_role("upload", "read", lacks=("read_all",))
    a = await user(client, "a@example.com", role)
    b = await user(client, "b@example.com", role, n=1, join="a@example.com")
    async with client_for(a) as first, client_for(b) as second:
        mine = await upload_ok(first)
        await second.get("/files")  # the first request creates the user's row (token-based auth)
        await first.get("/files")
        async with session_factory() as session:
            owner = (await session.execute(sa.select(AuthUser).where(AuthUser.email == "a@example.com"))).scalar_one()
            other = (await session.execute(sa.select(AuthUser).where(AuthUser.email == "b@example.com"))).scalar_one()
            file_id = uuid.UUID(mine["id"])
            await refs.check_attachable(session, file_id, owner, "image_id")  # the owner may
            for caller in (other, None):
                with pytest.raises(AppError) as refused:
                    await refs.check_attachable(session, file_id, caller, "image_id")
                assert refused.value.code == "invalid_reference" and refused.value.status_code == 422
            with pytest.raises(AppError) as missing:
                await refs.check_attachable(session, uuid.uuid4(), owner, "image_id")
            assert missing.value.code == "invalid_reference"
            # a quarantined file cannot be attached, even by its owner
            await session.execute(sa.update(StorFile).where(StorFile.id == file_id).values(status="quarantined"))
            await session.commit()
            with pytest.raises(AppError) as blocked:
                await refs.check_attachable(session, file_id, owner, "image_id")
            assert blocked.value.code == "invalid_reference"


# --- 8. tampering with stored bytes ---------------------------------------------------------------


@proxy_only
async def test_tampered_object_is_detected(
    client: AsyncClient, storage_env: MemoryBackend
) -> None:
    operator = pick_role("upload", "read", "operate")
    async with client_for(await user(client, "operator@example.com", operator)) as http:
        created = await upload_ok(http)
        row = (await rows())[0]
        original = storage_env.objects[row.storage_key]
        storage_env.objects[row.storage_key] = bytes(b ^ 0xFF for b in original)  # same size, other bytes
        response = await http.get(f"/files/{created['id']}/download")
        assert response.status_code == 200  # the headers were already sent when the hash was known
        await service.wait_for_background()
        mismatch = await events("download.integrity_mismatch", created["id"])
        assert len(mismatch) == 1 and mismatch[0].outcome == "error"
        assert (await rows())[0].status == "quarantined"  # and it is not served again
        assert (await http.get(f"/files/{created['id']}/download")).status_code == 409
        async with session_factory() as session:
            stored = await session.get(StorFile, row.id)
            assert stored is not None
            verdict = await service.rescan(session, stored, actor_id=None, info=service.RequestInfo())
        assert verdict == "tampered"
        assert (await rows())[0].status == "quarantined"


# --- 9. the audit trail ---------------------------------------------------------------------------


async def test_audit_trail_is_append_only(alice: AsyncClient) -> None:
    created = await upload_ok(alice)
    for statement in (
        "UPDATE stor_audit_log SET event = 'x'",
        "DELETE FROM stor_audit_log",
        "TRUNCATE TABLE stor_audit_log",
    ):
        async with engine.connect() as connection:
            with pytest.raises(DBAPIError):
                await connection.execute(sa.text(statement))
    assert len(await events(file_id=created["id"])) == 1  # untouched


async def test_audit_chain_detects_tampering(client: AsyncClient) -> None:
    role = pick_role("upload", "read", "operate")
    async with client_for(await user(client, "operator@example.com", role)) as http:
        created = await upload_ok(http)
        await http.get(f"/files/{created['id']}/download")
        trail = (await http.get(f"/files/{created['id']}/audit")).json()
        assert trail["chain_ok"] is True and trail["first_bad_seq"] is None
        assert [e["event"] for e in trail["entries"]][:1] == ["upload.accepted"]
        assert all("ip" in e for e in trail["entries"])

        async with engine.begin() as connection:  # someone with table rights edits history
            await connection.execute(sa.text("ALTER TABLE stor_audit_log DISABLE TRIGGER stor_audit_append_only"))
            try:
                await connection.execute(
                    sa.text("UPDATE stor_audit_log SET data = '{\"size\": 1}'::jsonb WHERE file_id = :id AND seq = 1"),
                    {"id": uuid.UUID(created["id"])},
                )
            finally:
                await connection.execute(sa.text("ALTER TABLE stor_audit_log ENABLE TRIGGER stor_audit_append_only"))
        tampered = (await http.get(f"/files/{created['id']}/audit")).json()
        assert tampered["chain_ok"] is False and tampered["first_bad_seq"] == 1


# --- 10. nothing leaks ----------------------------------------------------------------------------


async def test_secrets_never_leak(
    alice: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = "s3cr3t-value-that-must-never-leak-0123456789"
    key_id = "AKIAFAKEKEYIDFORTESTS"
    monkeypatch.setenv("STORAGE_SECRET_ACCESS_KEY", secret)
    monkeypatch.setenv("STORAGE_ACCESS_KEY_ID", key_id)
    config.get_storage_settings.cache_clear()
    settings = config.get_storage_settings()
    assert secret not in repr(settings) and secret not in str(settings.model_dump())
    assert redact.scrub_text(f"credentials {secret} and {key_id}") == "credentials [redacted] and [redacted]"

    created = await upload_ok(alice)
    responses = [
        await alice.get("/openapi.json"),
        await alice.get(f"/files/{created['id']}"),
        await alice.get(f"/files/{uuid.uuid4()}"),
        await alice.get("/files"),
    ]
    for response in responses:
        assert secret not in response.text and key_id not in response.text
    async with session_factory() as session:
        dumped = json.dumps([e.data for e in (await session.execute(sa.select(StorAuditLog))).scalars()])
    assert secret not in dumped and key_id not in dumped

    # A secret can also come from a file (Docker / Kubernetes secrets); both at once is ambiguous.
    secret_file = tmp_path / "secret"
    secret_file.write_text(secret + "\n")
    monkeypatch.delenv("STORAGE_SECRET_ACCESS_KEY")
    monkeypatch.setenv("STORAGE_SECRET_ACCESS_KEY_FILE", str(secret_file))
    config.get_storage_settings.cache_clear()
    assert config.get_storage_settings().storage_secret_access_key.get_secret_value() == secret  # type: ignore[union-attr]
    monkeypatch.setenv("STORAGE_SECRET_ACCESS_KEY", secret)
    config.get_storage_settings.cache_clear()
    with pytest.raises(config.StorageConfigError):
        config.get_storage_settings()


async def test_responses_hide_storage_internals(
    alice: AsyncClient, storage_env: MemoryBackend
) -> None:
    created = await upload_ok(alice)
    assert set(created) == {
        "id", "status", "shared", "original_name", "content_type", "size_bytes", "sha256",
        "created_by_id", "created_at", "scanned_at",
    }
    (key,) = storage_env.objects
    blobs = [
        json.dumps(created),
        (await alice.get("/openapi.json")).text,
        (await alice.get(f"/files/{uuid.uuid4()}")).text,
        (await alice.get("/files")).text,
    ]
    for blob in blobs:
        assert key not in blob and config.BUCKET not in blob and "storage_key" not in blob


# --- 11. configuration ----------------------------------------------------------------------------


def _fresh(monkeypatch: pytest.MonkeyPatch, **env: str) -> config.StorageSettings:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    config.get_storage_settings.cache_clear()
    return config.get_storage_settings()


def test_unsafe_settings_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    good = {"STORAGE_ENDPOINT_URL": "https://s3.example.com", "STORAGE_ACCESS_KEY_ID": "id", "STORAGE_SECRET_ACCESS_KEY": "secret"}
    _fresh(monkeypatch, **good, APP_ENV="production").check()  # a sound production setup passes
    bad: list[dict[str, str]] = [
        {**good, "APP_ENV": "production", "STORAGE_ENDPOINT_URL": "http://s3.example.com"},
        {**good, "APP_ENV": "production", "STORAGE_PUBLIC_ENDPOINT_URL": "http://files.example.com"},
        {**good, "APP_ENV": "production", "STORAGE_CREATE_BUCKET": "true"},
        {**good, "STORAGE_ENDPOINT_URL": "https://user:pass@s3.example.com"},
        {**good, "STORAGE_ENDPOINT_URL": "ftp://s3.example.com"},
        {**good, "STORAGE_SECRET_ACCESS_KEY": ""},  # an id without its secret
        {**good, "STORAGE_SSE": "rot13"},
        {**good, "STORAGE_SSE": "aws:kms"},  # no key id
        {**good, "STORAGE_ADDRESSING": "sideways"},
        {**good, "STORAGE_SCAN_TIMEOUT_SECONDS": "1"},
        {**good, "STORAGE_TRUSTED_PROXIES": "99"},
        {**good, "CLAMD_PORT": "0"},
    ]
    for env in bad:
        for name in good:
            monkeypatch.delenv(name, raising=False)
        for name in ("APP_ENV", "STORAGE_CREATE_BUCKET", "STORAGE_SSE", "STORAGE_ADDRESSING", "STORAGE_PUBLIC_ENDPOINT_URL", "STORAGE_SCAN_TIMEOUT_SECONDS", "STORAGE_TRUSTED_PROXIES", "CLAMD_PORT"):
            monkeypatch.delenv(name, raising=False)
        with pytest.raises(config.StorageConfigError):
            _fresh(monkeypatch, **env).check()


def test_a_minio_project_needs_an_endpoint_and_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "BACKEND", "minio")
    with pytest.raises(config.StorageConfigError):
        _fresh(monkeypatch).check()
    with pytest.raises(config.StorageConfigError):
        _fresh(monkeypatch, STORAGE_ENDPOINT_URL="https://s3.example.com").check()
    _fresh(
        monkeypatch,
        STORAGE_ENDPOINT_URL="https://s3.example.com",
        STORAGE_ACCESS_KEY_ID="id",
        STORAGE_SECRET_ACCESS_KEY="secret",
    ).check()


def test_blank_environment_values_count_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _fresh(
        monkeypatch,
        STORAGE_ENDPOINT_URL="",
        STORAGE_ACCESS_KEY_ID="",
        STORAGE_SECRET_ACCESS_KEY="",
        STORAGE_REGION="",
    )
    assert settings.storage_endpoint_url is None and settings.storage_secret_access_key is None
    if config.BACKEND == "s3":
        settings.check()  # on AWS the role supplies the credentials


# --- 13. crashes and clean-up ---------------------------------------------------------------------


async def test_maintenance_cleans_up_after_a_crash(
    alice: AsyncClient, storage_env: MemoryBackend
) -> None:
    created = await upload_ok(alice)
    user_id = uuid.UUID(created["created_by_id"])

    async def stale_pending(key: str, age: str) -> uuid.UUID:
        file_id = uuid.uuid4()
        storage_env.objects[key] = b"orphan"
        async with session_factory() as session:
            session.add(
                StorFile(
                    id=file_id, created_by_id=user_id, status="pending", shared=False,
                    original_name="crash.txt", declared_type="text/plain", detected_type="text/plain",
                    size_bytes=6, sha256="0" * 64, storage_key=key,
                )
            )
            await session.commit()
            await session.execute(
                sa.text(f"UPDATE stor_files SET updated_at = now() - interval '{age}' WHERE id = :id"),
                {"id": file_id},
            )
            await session.commit()
        return file_id

    old = await stale_pending(f"{config.KEY_PREFIX}/_/crash/old", "3 hours")
    young = await stale_pending(f"{config.KEY_PREFIX}/_/crash/young", "1 minute")
    assert await maintenance.purge_pending() == 1
    keys = {r.id: r for r in await rows()}
    assert old not in keys and young in keys  # only the stale one went
    assert f"{config.KEY_PREFIX}/_/crash/old" not in storage_env.objects
    assert f"{config.KEY_PREFIX}/_/crash/young" in storage_env.objects
    assert len(await events("maintenance.pending_purged")) == 1
    assert uuid.UUID(created["id"]) in keys  # real files are untouched

    digest = await maintenance.log_digest(datetime.now(UTC))
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    assert await maintenance.purge_audit() == 0  # nothing is old enough to go
    rescanned = await maintenance.rescan_old(10)
    assert rescanned == {}  # nothing is due: it was just scanned
