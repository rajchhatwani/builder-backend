"""Caps the size of an upload before it is read into a temporary file (generated).

The multipart parser spools the whole request body to disk before the route runs, so a limit checked
inside the route would come too late. This ASGI middleware counts bytes as they arrive and stops
the request the moment it is over the limit, whether or not the client declared a Content-Length.
"""

import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

import structlog
from starlette.types import ASGIApp, Receive, Scope, Send

logger = structlog.get_logger()

Message = MutableMapping[str, Any]

# Room for the multipart framing and the few small form fields around the file itself.
OVERHEAD_BYTES = 256 * 1024


class PayloadTooLarge(Exception):
    pass


class UploadSizeLimitMiddleware:
    def __init__(self, app: ASGIApp, *, path: str, max_file_bytes: int) -> None:
        self.app = app
        self.path = path
        self.limit = max_file_bytes + OVERHEAD_BYTES
        self.max_file_bytes = max_file_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != self.path:
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope["headers"]}
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > self.limit:
                    await self._reject(send)
                    return
            except ValueError:
                await self._reject(send, status=400, code="bad_request", message="bad Content-Length")
                return

        seen = 0
        started = False

        async def counted_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.limit:
                    raise PayloadTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counted_receive, tracked_send)
        except PayloadTooLarge:
            if started:
                raise
            await self._reject(send)

    async def _reject(
        self,
        send: Callable[[Message], Awaitable[None]],
        *,
        status: int = 413,
        code: str = "file_too_large",
        message: str | None = None,
    ) -> None:
        logger.warning("upload_refused", status=status, code=code)  # no audit row: not signed in yet
        mb = self.max_file_bytes // (1024 * 1024)
        body = json.dumps(
            {
                "code": code,
                "message": message or f"the file is larger than the {mb} MB limit",
                "details": [],
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
