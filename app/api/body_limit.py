"""A smaller body cap for spec writes (whole-spec PUT and the per-block PUTs), enforced on the bytes
actually received (chunked bodies included), answering 413 before the handler or the JSON parser runs.

The app-wide cap (`max_request_bytes`) still applies to everything else; this one is
`max_spec_write_bytes` (default 1 MiB). Pure ASGI: the body is buffered up to the cap, then replayed.
"""

import re

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_SPEC_WRITE = re.compile(
    r"^/projects/[^/]+/(spec|behavior/[^/]+|authorization|observability|deployment|documents)/?$"
)


def is_spec_write(method: str, path: str) -> bool:
    return method.upper() == "PUT" and _SPEC_WRITE.match(path) is not None


class SpecWriteLimit:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_spec_write(scope["method"], scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope["headers"]}
        declared = headers.get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.max_bytes:
            await self._too_large(send)
            return
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":  # the client went away
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.max_bytes:
                await self._too_large(send)
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

    async def _too_large(self, send: Send) -> None:
        body = (
            b'{"code":"payload_too_large","message":"spec write is too large","details":[]}'
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
