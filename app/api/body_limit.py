"""A smaller body cap for spec writes (whole-spec PUT and the per-block PUTs), enforced on the bytes
actually received (chunked bodies included), answering 413 before the handler or the JSON parser runs.

The app-wide cap (`max_request_bytes`) still applies to everything else; this one is
`max_spec_write_bytes` (default 1 MiB). Pure ASGI: the body is buffered up to the cap, then replayed.
"""

import re

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.data_import import MAX_BYTES as IMPORT_FILE_MAX_BYTES

_SPEC_WRITE = re.compile(
    r"^/projects/[^/]+/(spec|behavior/[^/]+|authorization|observability|deployment|documents)/?$"
)


_INTAKE = re.compile(r"^/projects/[^/]+/requirements/intake/?$")
INTAKE_MAX_BYTES = 13 * 1024 * 1024  # 5 files x 5 MB is capped to 12 MB of files, plus form overhead


_IMPORT = re.compile(r"^/projects/[^/]+/imports/?$")
IMPORT_MAX_BYTES = IMPORT_FILE_MAX_BYTES + 256 * 1024  # the CSV cap plus multipart overhead (L8)


def is_import_upload(method: str, path: str) -> bool:
    return method.upper() == "POST" and _IMPORT.match(path) is not None


def is_intake(method: str, path: str) -> bool:
    return method.upper() == "POST" and _INTAKE.match(path) is not None


def is_spec_write(method: str, path: str) -> bool:
    return method.upper() == "PUT" and _SPEC_WRITE.match(path) is not None


class SpecWriteLimit:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        code = "payload_too_large"
        if scope["type"] == "http" and is_import_upload(scope["method"], scope.get("path", "")):
            limit, code = IMPORT_MAX_BYTES, "import_too_large"
        elif scope["type"] == "http" and is_intake(scope["method"], scope.get("path", "")):
            limit = INTAKE_MAX_BYTES
        elif scope["type"] == "http" and is_spec_write(scope["method"], scope.get("path", "")):
            limit = self.max_bytes
        else:
            await self.app(scope, receive, send)
            return
        await self._limited(scope, receive, send, limit, code)

    async def _limited(
        self, scope: Scope, receive: Receive, send: Send, limit: int, code: str = "payload_too_large"
    ) -> None:
        headers = {k.lower(): v for k, v in scope["headers"]}
        declared = headers.get(b"content-length", b"")
        if declared.isdigit() and int(declared) > limit:
            await self._too_large(send, code)
            return
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":  # the client went away
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > limit:
                await self._too_large(send, code)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        sent = False

        async def replay() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    async def _too_large(self, send: Send, code: str = "payload_too_large") -> None:
        body = (
            b'{"code":"' + code.encode() + b'","message":"request body is too large","details":[]}'
        )
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
