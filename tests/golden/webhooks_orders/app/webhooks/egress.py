"""The only code that opens a connection for an outgoing webhook (generated). Standard library only.

Every request goes through app.webhooks.ssrf first: the URL is parsed, the name is resolved once, every
answer must be public, and the connection goes to the chosen IP LITERALLY (TLS still checks the certificate
against the original host name). After connecting, the peer address is checked again. Redirects are NEVER
followed: a 3xx answer is returned to the caller as a failure. Limits: the whole exchange has a deadline,
the response head is at most 16 KB, the response body is not read at all (it is never stored or logged),
the request body is capped by the caller.
"""

import asyncio
import ipaddress
import re
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.webhooks import ssrf

MAX_HEAD_BYTES = 16 * 1024
USER_AGENT = "webhook-delivery/1"
_STATUS = re.compile(rb"^HTTP/1\.[01] ([2-5][0-9]{2})(?: |\r|$)")
_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_HEADER_VALUE = re.compile(r"^[\x20-\x7e]{0,2048}$")


class EgressError(Exception):
    """A failed exchange. `code` is stable and safe to store; `retryable` says if trying again can help."""

    def __init__(self, code: str, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class Response:
    status: int


Connector = Callable[[str, int, "ssl.SSLContext | None", str], Awaitable[tuple[Any, Any]]]


async def open_connection(ip: str, port: int, context: ssl.SSLContext | None, server_hostname: str) -> tuple[Any, Any]:
    return await asyncio.open_connection(
        ip, port, ssl=context, server_hostname=server_hostname if context else None, limit=MAX_HEAD_BYTES
    )


CONNECTOR: Connector = open_connection  # tests replace it with an in-memory fake; production never does


def _tls() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _request_bytes(target: ssrf.Target, body: bytes, headers: dict[str, str]) -> bytes:
    lines = [
        f"POST {target.request_target} HTTP/1.1",
        f"Host: {target.host_header}",
        f"User-Agent: {USER_AGENT}",
        "Content-Type: application/json",
        f"Content-Length: {len(body)}",
        "Connection: close",
    ]
    for name, value in headers.items():
        if not _HEADER_NAME.fullmatch(name) or not _HEADER_VALUE.fullmatch(value):
            raise ssrf.Blocked("invalid_header")  # never write a header that could split the request
        lines.append(f"{name}: {value}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body


async def _exchange(target: ssrf.Target, ip: str, request: bytes) -> Response:
    context = _tls() if target.scheme == "https" else None
    try:
        reader, writer = await CONNECTOR(ip, target.port, context, target.host)
    except ssl.SSLError:
        raise EgressError("tls_failed", True) from None
    except OSError:
        raise EgressError("connect_failed", True) from None
    try:
        peer = writer.get_extra_info("peername")
        try:
            peer_ip = ipaddress.ip_address(str(peer[0]).split("%", 1)[0])
        except (TypeError, IndexError, ValueError):
            raise ssrf.Blocked("address_not_public") from None
        if not ssrf.is_public_ip(peer_ip):  # defence in depth: the connected peer is public too
            raise ssrf.Blocked("address_not_public")
        writer.write(request)
        await writer.drain()
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
            raise EgressError("bad_response", True) from None
        if len(head) > MAX_HEAD_BYTES:
            raise EgressError("bad_response", True)
        match = _STATUS.match(head)
        if match is None:
            raise EgressError("bad_response", True)
        return Response(status=int(match.group(1)))
    except ssl.SSLError:
        raise EgressError("tls_failed", True) from None
    except OSError:
        raise EgressError("connect_failed", True) from None
    finally:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), 2.0)
        except (OSError, TimeoutError, ssl.SSLError):
            pass


async def post(
    url: str, body: bytes, headers: dict[str, str], *, policy: ssrf.Policy, timeout: float
) -> Response:
    """POST `body` to `url`. Raises ssrf.Blocked (never retry) or EgressError (retry when `retryable`)."""
    target = ssrf.parse_target(url, policy)
    request = _request_bytes(target, body, headers)
    try:
        async with asyncio.timeout(timeout):
            try:
                ip = await ssrf.pin(target)
            except ssrf.ResolveFailed:
                raise EgressError("dns_failed", True) from None
            return await _exchange(target, ip, request)
    except TimeoutError:
        raise EgressError("timeout", True) from None
