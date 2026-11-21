"""Fixtures for webhook tests (generated). Nothing here touches a network: names resolve through a table
and connections go to in-memory fake servers.

    from tests._webhooks_support import net

`net.resolve["hooks.example.com"] = ["93.184.216.34"]` decides what a name resolves to (a list of lists gives a
different answer per lookup); `net.serve("93.184.216.34", status=200)` answers connections to that IP;
`net.connects` and `net.requests` record what happened."""

import asyncio
import ssl
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.webhooks import egress, ssrf

KEY = "webhooks-test-vault-key-0123456789abcdef"


@dataclass
class Request:
    ip: str
    port: int
    hostname: str
    tls: bool
    raw: bytes

    @property
    def head(self) -> str:
        return self.raw.split(b"\r\n\r\n", 1)[0].decode("ascii")

    @property
    def body(self) -> bytes:
        return self.raw.split(b"\r\n\r\n", 1)[1]

    def header(self, name: str) -> str | None:
        for line in self.head.split("\r\n")[1:]:
            key, _, value = line.partition(": ")
            if key.lower() == name.lower():
                return value
        return None


class _Writer:
    def __init__(self, net: "FakeNet", ip: str, port: int, hostname: str, tls: bool, peer: str) -> None:
        self._net, self._peer, self._port = net, peer, port
        self.request = Request(ip, port, hostname, tls, b"")

    def write(self, data: bytes) -> None:
        self.request.raw += data

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None

    def get_extra_info(self, name: str) -> Any:
        return (self._peer, self._port) if name == "peername" else None


@dataclass
class FakeNet:
    resolve: dict[str, Any] = field(default_factory=dict)  # host -> [ip, ...] or [[ip, ...], [ip, ...]] per lookup
    lookups: list[str] = field(default_factory=list)
    connects: list[tuple[str, int, str]] = field(default_factory=list)  # (ip, port, hostname)
    requests: list[Request] = field(default_factory=list)
    answers: dict[str, Callable[[Request], bytes]] = field(default_factory=dict)
    peer_override: dict[str, str] = field(default_factory=dict)  # ip -> the peer address the "socket" reports
    unreachable: set[str] = field(default_factory=set)

    def serve(self, ip: str, status: int = 200, headers: str = "") -> None:
        self.answers[ip] = lambda _r: f"HTTP/1.1 {status} X\r\nContent-Length: 0\r\n{headers}\r\n".encode()

    def serve_sequence(self, ip: str, statuses: list[int]) -> None:
        queue = list(statuses)
        self.answers[ip] = lambda _r: f"HTTP/1.1 {queue.pop(0) if len(queue) > 1 else queue[0]} X\r\n\r\n".encode()

    async def resolver(self, host: str, port: int) -> list[str]:
        self.lookups.append(host)
        entry = self.resolve.get(host)
        if entry is None:
            raise ssrf.ResolveFailed("dns")
        if entry and isinstance(entry[0], list):
            count = self.lookups.count(host)
            return list(entry[min(count, len(entry)) - 1])
        return list(entry)

    async def connector(self, ip: str, port: int, context: ssl.SSLContext | None, hostname: str) -> tuple[Any, Any]:
        self.connects.append((ip, port, hostname))
        if ip in self.unreachable or ip not in self.answers:
            raise ConnectionRefusedError
        writer = _Writer(self, ip, port, hostname, context is not None, self.peer_override.get(ip, ip))
        reader = asyncio.StreamReader()
        original = writer.write

        def write(data: bytes) -> None:
            original(data)
            if b"\r\n\r\n" in writer.request.raw and not reader._eof:  # noqa: SLF001
                self.requests.append(writer.request)
                reader.feed_data(self.answers[ip](writer.request))
                reader.feed_eof()

        writer.write = write  # type: ignore[method-assign]
        return reader, writer


@pytest.fixture
def net(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeNet]:
    """APP_ENV=test, a test vault key, and the fake network in place of DNS and sockets."""
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("PROVIDER_VAULT_KEY", KEY)
    monkeypatch.setenv("PROVIDER_VAULT_KEY_VERSION", "1")
    monkeypatch.delenv("PROVIDER_VAULT_KEY_PREVIOUS", raising=False)
    fake = FakeNet()
    monkeypatch.setattr(ssrf, "RESOLVER", fake.resolver)
    monkeypatch.setattr(egress, "CONNECTOR", fake.connector)
    yield fake
