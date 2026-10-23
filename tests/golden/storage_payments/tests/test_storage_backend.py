"""The S3 adapter (app/storage/backend.py) against botocore's stubber (generated): no network, but the
real adapter code and the real boto3 client, so the way it reads S3's answers is tested."""

import io
from collections.abc import Iterator
from urllib.parse import parse_qs, urlsplit

import pytest
from botocore.stub import Stubber

from app.storage import config
from app.storage.backend import BackendUnavailable, ObjectMissing, S3Backend

ENV = {
    "STORAGE_ENDPOINT_URL": "https://s3.example.test",
    "STORAGE_ACCESS_KEY_ID": "test-key-id",
    "STORAGE_SECRET_ACCESS_KEY": "test-secret-key-value",
}


def make(monkeypatch: pytest.MonkeyPatch, **extra: str) -> S3Backend:
    for name in ("STORAGE_ENDPOINT_URL", "STORAGE_PUBLIC_ENDPOINT_URL", "APP_ENV", "STORAGE_SSE"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {**ENV, **extra}.items():
        monkeypatch.setenv(name, value)
    config.get_storage_settings.cache_clear()
    return S3Backend(config.get_storage_settings())


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    yield
    config.get_storage_settings.cache_clear()


def stub(backend: S3Backend) -> Stubber:
    stubber = Stubber(backend._client)
    stubber.activate()
    return stubber


async def test_a_missing_bucket_is_a_failure_not_a_missing_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = make(monkeypatch)
    stubber = stub(backend)
    stubber.add_client_error("head_bucket", service_error_code="404", http_status_code=404)
    with pytest.raises(BackendUnavailable):
        await backend.check()


async def test_a_missing_object_is_reported_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = make(monkeypatch)
    stubber = stub(backend)
    stubber.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)
    with pytest.raises(ObjectMissing):
        async for _ in backend.stream("uploads/_/2026/01/x"):
            pass


async def test_other_errors_never_look_like_a_missing_object(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = make(monkeypatch)
    stubber = stub(backend)
    stubber.add_client_error("get_object", service_error_code="AccessDenied", http_status_code=403)
    with pytest.raises(BackendUnavailable):
        async for _ in backend.stream("uploads/_/2026/01/x"):
            pass


async def test_the_bucket_is_created_in_development_when_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = make(monkeypatch, STORAGE_CREATE_BUCKET="true")
    stubber = stub(backend)
    stubber.add_client_error("head_bucket", service_error_code="404", http_status_code=404)
    stubber.add_response("create_bucket", {})
    await backend.ensure_bucket()
    stubber.assert_no_pending_responses()


async def test_an_existing_bucket_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = make(monkeypatch, STORAGE_CREATE_BUCKET="true")
    stubber = stub(backend)
    stubber.add_response("head_bucket", {})
    await backend.ensure_bucket()
    stubber.assert_no_pending_responses()


async def test_the_bucket_is_never_created_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = make(monkeypatch, APP_ENV="production", STORAGE_CREATE_BUCKET="true")
    stubber = stub(backend)
    stubber.add_client_error("head_bucket", service_error_code="404", http_status_code=404)
    with pytest.raises(BackendUnavailable):
        await backend.ensure_bucket()  # a create_bucket call would be an unexpected call for the stub


async def test_the_bucket_is_not_created_unless_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = make(monkeypatch)
    stubber = stub(backend)
    stubber.add_client_error("head_bucket", service_error_code="404", http_status_code=404)
    with pytest.raises(BackendUnavailable):
        await backend.ensure_bucket()


async def test_a_failed_upload_is_unavailable_and_says_nothing_about_the_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = make(monkeypatch)
    stubber = stub(backend)
    stubber.add_client_error(
        "put_object", service_error_code="InternalError", http_status_code=500, service_message="boom"
    )
    with pytest.raises(BackendUnavailable) as raised:
        await backend.put("uploads/_/2026/01/x", io.BytesIO(b"data"), sha256="0" * 64)
    assert "boom" not in str(raised.value) and "s3.example.test" not in str(raised.value)


async def test_delete_survives_a_server_that_cannot_list_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = make(monkeypatch)
    stubber = stub(backend)
    stubber.add_response("delete_object", {})
    stubber.add_client_error(
        "list_object_versions", service_error_code="AccessDenied", http_status_code=403
    )
    await backend.delete("uploads/_/2026/01/x")
    stubber.assert_no_pending_responses()


async def test_delete_removes_old_versions_too(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = make(monkeypatch)
    stubber = stub(backend)
    key = "uploads/_/2026/01/x"
    stubber.add_response("delete_object", {})
    stubber.add_response(
        "list_object_versions",
        {
            "Versions": [{"Key": key, "VersionId": "v1"}, {"Key": key + "-other", "VersionId": "v9"}],
            "DeleteMarkers": [{"Key": key, "VersionId": "v2"}],
        },
    )
    stubber.add_response("delete_object", {}, {"Bucket": config.BUCKET, "Key": key, "VersionId": "v1"})
    stubber.add_response("delete_object", {}, {"Bucket": config.BUCKET, "Key": key, "VersionId": "v2"})
    await backend.delete(key)
    stubber.assert_no_pending_responses()  # and "-other" (a different key) was left alone


def test_presigned_links_carry_the_safe_response_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = make(monkeypatch)
    url = backend.presign("uploads/_/2026/01/x", filename_header='attachment; filename="a.pdf"', ttl=60)
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert parts.scheme == "https" and parts.hostname == "s3.example.test"
    assert query["X-Amz-Expires"] == ["60"]
    assert query["response-content-type"] == ["application/octet-stream"]
    assert query["response-content-disposition"] == ['attachment; filename="a.pdf"']
    assert "test-secret-key-value" not in url and "X-Amz-Signature" in query


def test_presigned_links_use_the_public_address_when_there_is_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = make(monkeypatch, STORAGE_PUBLIC_ENDPOINT_URL="https://files.example.test")
    url = backend.presign("uploads/x", filename_header="attachment", ttl=30)
    assert urlsplit(url).hostname == "files.example.test"


def test_checksums_are_only_sent_when_the_server_requires_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = make(monkeypatch)
    cfg = backend._client.meta.config
    assert cfg.request_checksum_calculation == "when_required"
    assert cfg.response_checksum_validation == "when_required"
    assert cfg.signature_version == "s3v4"


def test_encryption_default_depends_on_where_the_bucket_lives(monkeypatch: pytest.MonkeyPatch) -> None:
    custom = make(monkeypatch)
    assert "ServerSideEncryption" not in custom._extra_args("0" * 64)  # a custom server may lack it
    monkeypatch.delenv("STORAGE_ENDPOINT_URL")
    config.get_storage_settings.cache_clear()
    aws = S3Backend(config.get_storage_settings())
    assert aws._extra_args("0" * 64)["ServerSideEncryption"] == "AES256"
    forced = make(monkeypatch, STORAGE_SSE="none")
    assert "ServerSideEncryption" not in forced._extra_args("0" * 64)


def test_objects_are_written_with_a_generic_type_and_only_a_hash_as_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extra = make(monkeypatch)._extra_args("a" * 64)
    assert extra["ContentType"] == "application/octet-stream"
    assert extra["Metadata"] == {"sha256": "a" * 64}
