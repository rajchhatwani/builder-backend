"""D-1: the multipart NUL guard parses bodies only on the intake route."""

import pytest
from starlette.requests import Request

from app.api.input_guard import reject_nul_characters
from app.exceptions import AppError

PID = "11111111-1111-1111-1111-111111111111"


def _request(path: str, body: bytes, boundary: str = "xx") -> Request:
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http", "method": "POST", "path": path, "query_string": b"", "headers": [
            (b"content-type", f"multipart/form-data; boundary={boundary}".encode()),
            (b"content-length", str(len(body)).encode()),
        ],
    }
    return Request(scope, receive)


def _multipart(value: bytes) -> bytes:
    return b'--xx\r\nContent-Disposition: form-data; name="prompt"\r\n\r\n' + value + b"\r\n--xx--\r\n"


async def test_nul_in_an_intake_text_field_is_still_rejected() -> None:
    with pytest.raises(AppError) as exc:
        await reject_nul_characters(_request(f"/projects/{PID}/requirements/intake", _multipart(b"a\x00b")))
    assert exc.value.status_code == 422


async def test_a_multipart_post_to_another_route_is_not_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(self: Request, **kw: object) -> None:
        raise AssertionError("the guard parsed a multipart body of an unrelated route")

    monkeypatch.setattr(Request, "form", boom)
    await reject_nul_characters(_request(f"/projects/{PID}/entities", _multipart(b"a\x00b")))
