"""F-0899: the generated NUL guard must scan every JSON-parsed content type (json and +json)."""

from pathlib import Path

import pytest
from starlette.requests import Request

TPL = Path("app/core/generator/features/crud/templates/app/core/errors.py.tpl")


def _guard():
    ns: dict[str, object] = {"__name__": "gen_errors"}
    exec(compile(TPL.read_text(), str(TPL), "exec"), ns)
    return ns["reject_nul_characters"], ns["AppError"]


def _request(content_type: str, body: bytes) -> Request:
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http", "method": "POST", "path": "/x", "query_string": b"",
        "headers": [(b"content-type", content_type.encode())],
    }
    return Request(scope, receive)


@pytest.mark.parametrize(
    "ctype",
    ["application/json", "application/vnd.api+json", "application/merge-patch+json; charset=utf-8"],
)
@pytest.mark.parametrize("body", [b'{"a":"b\x00"}', b'{"a":"b\\u0000"}'])
async def test_nul_in_json_family_body_is_refused(ctype: str, body: bytes) -> None:
    guard, app_error = _guard()
    with pytest.raises(app_error):
        await guard(_request(ctype, body))


async def test_clean_plus_json_passes() -> None:
    guard, _ = _guard()
    await guard(_request("application/vnd.api+json", b'{"a":"b"}'))
