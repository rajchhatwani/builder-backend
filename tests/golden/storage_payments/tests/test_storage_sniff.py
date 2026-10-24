"""Unit tests of the file module's building blocks (generated): type detection, file names, the
scanner client over a real socket, and the upload size cap. They need no database and no object store."""

import socket
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest

from app.storage import clamav, names, sniff
from app.storage.limits import OVERHEAD_BYTES, UploadSizeLimitMiddleware
from tests.fake_clamd import MARKER, SIGNATURE, FakeClamd

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PDF = b"%PDF-1.7\n" + b"x" * 32
EXE = b"MZ\x90\x00" + b"\x00" * 60


# --- type detection -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("head", "mime"),
    [
        (PNG, "image/png"),
        (JPEG, "image/jpeg"),
        (b"GIF89a" + b"\x00" * 20, "image/gif"),
        (b"RIFF\x24\x00\x00\x00WEBPVP8 ", "image/webp"),
        (PDF, "application/pdf"),
        (b"PK\x03\x04" + b"\x00" * 20, "application/zip"),
        (b"PK\x03\x04\x14\x00\x00\x00\x08\x00[Content_Types].xml word/document.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        (b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 20, "video/mp4"),
        (EXE, "application/vnd.microsoft.portable-executable"),
        (b"\x7fELF\x02\x01\x01" + b"\x00" * 20, "application/x-executable"),
        (b"#!/bin/sh\necho hi\n", "text/x-shellscript"),
        (b"hello, world\n", "text/plain"),
        (b'{"a": 1}', "text/plain"),
        (b"id,name\n1,Ann\n", "text/plain"),
        (b"<!DOCTYPE html><html><body>x</body></html>", "text/html"),
        (b"  <html><script>alert(1)</script>", "text/html"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', "image/svg+xml"),
        (b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>', "image/svg+xml"),
        (b'<?xml version="1.0"?><note/>', "application/xml"),
        (b"\x00\x01\x02\x03binary\xff\xfe", "application/octet-stream"),
        (b"", "application/octet-stream"),
    ],
)
def test_detect(head: bytes, mime: str) -> None:
    assert sniff.detect(head).mime == mime


def test_text_with_a_cut_off_character_is_still_text() -> None:
    head = ("é" * 4000).encode()[:-1]  # the last character is cut in half
    assert sniff.detect(head).mime == "text/plain"


def test_text_with_invalid_bytes_inside_is_not_text() -> None:
    assert sniff.detect(b"hello \xff\xfe\xfa world and more text").mime == "application/octet-stream"


def test_allowlist_rules() -> None:
    png, pdf, exe, text = (sniff.detect(x) for x in (PNG, PDF, EXE, b"a,b\n1,2\n"))
    assert sniff.type_allowed((), exe, "application/octet-stream")  # empty list = any type
    assert sniff.type_allowed(("image/png",), png, "image/png")
    assert sniff.type_allowed(("image/*",), png, "application/octet-stream")  # bytes decide
    assert not sniff.type_allowed(("image/*",), exe, "image/png")  # a renamed executable
    assert not sniff.type_allowed(("image/png",), pdf, "image/png")
    assert sniff.type_allowed(("text/csv",), text, "text/csv")  # text has no magic number
    assert not sniff.type_allowed(("text/csv",), text, "application/pdf")
    assert not sniff.type_allowed(("text/csv",), png, "text/csv")  # not text at all


def test_declared_type_is_cleaned_up() -> None:
    assert sniff.normalize_declared("Text/Plain; charset=utf-8") == "text/plain"
    assert sniff.normalize_declared(None) == "application/octet-stream"
    assert sniff.normalize_declared("not a type") == "application/octet-stream"
    assert sniff.normalize_declared("a/b\r\nX-Evil: 1") == "application/octet-stream"


def test_only_plain_images_keep_their_type_when_served() -> None:
    assert sniff.served_type("image/png") == "image/png"
    for risky in ("text/html", "image/svg+xml", "application/pdf", "application/xml", "text/plain"):
        assert sniff.served_type(risky) == "application/octet-stream"


# --- file names ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\x\\evil.exe", "evil.exe"),
        ("na\x00me.txt", "name.txt"),
        ("invoice\u202egpj.exe", "invoicegpj.exe"),
        ("  .hidden  ", "hidden"),
        ("a<b>c:d|e?.txt", "a_b_c_d_e_.txt"),
        ("", "file"),
        (None, "file"),
        ("...", "file"),
        ("CON", "_CON"),
        ("nul.txt", "_nul.txt"),
        ("tab\tand\nnewline.txt", "tabandnewline.txt"),
    ],
)
def test_safe_filename(raw: str | None, expected: str) -> None:
    assert names.safe_filename(raw) == expected


def test_long_names_keep_their_extension() -> None:
    result = names.safe_filename("a" * 400 + ".pdf")
    assert len(result) <= names.MAX_NAME_LENGTH and result.endswith(".pdf")
    assert len(names.safe_filename("b" * 400)) <= names.MAX_NAME_LENGTH


def test_content_disposition_cannot_be_broken_out_of() -> None:
    header = names.content_disposition('we"ird\\name.txt')
    assert header.startswith('attachment; filename="')
    assert '"ird' not in header and "\\" not in header.split("filename*=")[0].split('filename="')[1]
    assert "\r" not in header and "\n" not in header
    unicode_header = names.content_disposition("résumé.pdf")
    assert "filename*=UTF-8''r%C3%A9sum%C3%A9.pdf" in unicode_header
    assert unicode_header.isascii()
    assert names.content_disposition("a.png", inline=True).startswith("inline;")


def test_storage_key_is_made_of_ids_and_a_date_only() -> None:
    import datetime
    import uuid

    file_id, tenant = uuid.uuid4(), uuid.uuid4()
    now = datetime.datetime(2026, 3, 9, tzinfo=datetime.UTC)
    assert names.make_key("uploads", tenant, file_id, now) == f"uploads/{tenant}/2026/03/{file_id}"
    assert names.make_key("uploads", None, file_id, now) == f"uploads/_/2026/03/{file_id}"


# --- the scanner client, over a real socket -----------------------------------------------------


@pytest.fixture
def clamd() -> Iterator[FakeClamd]:
    server = FakeClamd().start()
    yield server
    server.stop()


async def scan(server: FakeClamd, data: bytes, timeout: float = 5.0) -> clamav.ScanResult:
    import io

    return await clamav.scan(io.BytesIO(data), host="127.0.0.1", port=server.port, timeout=timeout)


async def test_clean_file(clamd: FakeClamd) -> None:
    result = await scan(clamd, b"just a file")
    assert result.clean and result.signature is None
    assert clamd.commands == [b"zINSTREAM\x00"]


async def test_infected_file(clamd: FakeClamd) -> None:
    result = await scan(clamd, b"before " + MARKER + b" after")
    assert not result.clean and result.signature == SIGNATURE


async def test_a_large_file_is_streamed_in_correct_chunks(clamd: FakeClamd) -> None:
    data = bytes(range(256)) * 20_000  # 5 MB, many chunks
    assert (await scan(clamd, data)).clean
    assert clamd.scanned == [data]
    assert clamd.framing_errors == 0


@pytest.mark.parametrize("mode", ["error", "garbage", "unknown", "close"])
async def test_any_answer_that_is_not_a_clear_verdict_fails_closed(clamd: FakeClamd, mode: str) -> None:
    clamd.mode = mode
    with pytest.raises(clamav.ScannerUnavailable):
        await scan(clamd, b"x" * 100)


async def test_a_file_over_the_daemon_limit_fails_closed(clamd: FakeClamd) -> None:
    clamd.stream_max_length = 1000
    with pytest.raises(clamav.ScannerUnavailable):
        await scan(clamd, b"x" * 500_000)


async def test_a_scan_that_takes_too_long_fails_closed(clamd: FakeClamd) -> None:
    clamd.mode = "hang"
    with pytest.raises(clamav.ScannerUnavailable):
        await scan(clamd, b"x" * 100, timeout=0.5)


async def test_a_scanner_that_cannot_be_reached_fails_closed() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    import io

    with pytest.raises(clamav.ScannerUnavailable):
        await clamav.scan(io.BytesIO(b"x"), host="127.0.0.1", port=port, timeout=2)


async def test_ping_and_version(clamd: FakeClamd) -> None:
    clamav.reset_version_cache()
    assert await clamav.ping("127.0.0.1", clamd.port)
    assert (await clamav.engine_version("127.0.0.1", clamd.port) or "").startswith("ClamAV")
    clamav.reset_version_cache()


# --- the upload size cap ------------------------------------------------------------------------


CALLS: list[int] = []  # every time the wrapped app actually ran


async def _echo_size(scope, receive, send) -> None:  # type: ignore[no-untyped-def]
    CALLS.append(1)
    total = 0
    while True:
        message = await receive()
        total += len(message.get("body", b""))
        if not message.get("more_body"):
            break
    body = str(total).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def _client(limit: int) -> httpx.AsyncClient:
    app = UploadSizeLimitMiddleware(_echo_size, path="/files", max_file_bytes=limit)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_a_body_within_the_limit_passes() -> None:
    async with _client(1000) as client:
        response = await client.post("/files", content=b"x" * 2000)
    assert response.status_code == 200 and response.text == "2000"


async def test_a_declared_oversize_body_is_refused_at_once() -> None:
    CALLS.clear()
    async with _client(1000) as client:
        response = await client.post("/files", content=b"x" * (1000 + OVERHEAD_BYTES + 1))
    assert response.status_code == 413
    assert response.json()["code"] == "file_too_large"
    assert CALLS == []  # the application never saw the request


async def test_a_body_that_lies_about_its_size_is_cut_off() -> None:
    async def chunks() -> AsyncIterator[bytes]:  # no Content-Length: counted as it arrives
        for _ in range(40):
            yield b"x" * 10_000

    async with _client(1000) as client:
        response = await client.post("/files", content=chunks())
    assert response.status_code == 413


async def test_other_routes_are_not_limited() -> None:
    async with _client(1000) as client:
        response = await client.post("/other", content=b"x" * (1000 + OVERHEAD_BYTES + 5))
    assert response.status_code == 200
