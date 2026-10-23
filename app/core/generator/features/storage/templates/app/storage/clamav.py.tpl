"""A small client for ClamAV's clamd daemon (generated), written with the standard library.

It speaks the INSTREAM command of the clamd protocol: the command, then the data in chunks that are
each preceded by their length as four bytes (big endian), then a zero length to end. clamd answers
`stream: OK`, `stream: <signature> FOUND` or `... ERROR`. The Python wrappers around this protocol
are unmaintained, so there is no dependency to keep patched.

Everything fails closed: anything that is not a clear "OK" or "FOUND" is `ScannerUnavailable`, and the
caller must treat that as "not scanned", never as "clean". clamd itself has no authentication or
encryption, so it must only be reachable from this application (private network).
"""

import asyncio
import re
import struct
import time
from dataclasses import dataclass
from typing import BinaryIO

CHUNK_SIZE = 128 * 1024
_SIGNATURE_RE = re.compile(r"[A-Za-z0-9._:+/() -]{1,128}")
_VERSION_TTL_SECONDS = 300


class ScannerUnavailable(Exception):
    """The scan did not produce a verdict. The file must be treated as unscanned."""


@dataclass(frozen=True)
class ScanResult:
    clean: bool
    signature: str | None = None  # the detection name when not clean (sanitised)


def _parse_reply(reply: str) -> ScanResult:
    text = reply.strip("\x00\r\n ")
    if text == "stream: OK":
        return ScanResult(clean=True)
    if text.startswith("stream: ") and text.endswith(" FOUND"):
        name = text[len("stream: ") : -len(" FOUND")]
        return ScanResult(clean=False, signature=name if _SIGNATURE_RE.fullmatch(name) else "unknown")
    raise ScannerUnavailable("the scanner gave no usable answer")


async def _read_all(reader: asyncio.StreamReader, limit: int = 4096) -> bytes:
    data = b""
    while len(data) < limit:
        piece = await reader.read(1024)
        if not piece:
            break
        data += piece
    return data


async def _instream(file: BinaryIO, host: str, port: int) -> ScanResult:
    try:
        reader, writer = await asyncio.open_connection(host, port)
    except OSError as exc:
        raise ScannerUnavailable("cannot reach the scanner") from exc
    try:
        try:
            writer.write(b"zINSTREAM\x00")
            while True:
                chunk = await asyncio.to_thread(file.read, CHUNK_SIZE)
                if not chunk:
                    break
                writer.write(struct.pack("!I", len(chunk)) + chunk)
                await writer.drain()
            writer.write(struct.pack("!I", 0))
            await writer.drain()
        except OSError:
            # clamd closes the connection with an error message when it refuses the stream (for
            # example because it is over StreamMaxLength); the message is read below.
            pass
        reply = (await _read_all(reader)).decode("utf-8", "replace")
    except OSError as exc:
        raise ScannerUnavailable("lost the connection to the scanner") from exc
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
    return _parse_reply(reply)


async def scan(file: BinaryIO, *, host: str, port: int, timeout: float) -> ScanResult:
    """Scan `file` from its current position to its end. Raises ScannerUnavailable on any doubt."""
    try:
        return await asyncio.wait_for(_instream(file, host, port), timeout)
    except TimeoutError as exc:
        raise ScannerUnavailable("the scan timed out") from exc


async def _command(command: bytes, host: str, port: int, timeout: float) -> str:
    async def run() -> str:
        reader, writer = await asyncio.open_connection(host, port)
        try:
            writer.write(command)
            await writer.drain()
            return (await _read_all(reader)).decode("utf-8", "replace").strip("\x00\r\n ")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    try:
        return await asyncio.wait_for(run(), timeout)
    except (OSError, TimeoutError) as exc:
        raise ScannerUnavailable("cannot reach the scanner") from exc


async def ping(host: str, port: int, timeout: float = 5.0) -> bool:
    return await _command(b"zPING\x00", host, port, timeout) == "PONG"


_version_cache: tuple[float, str | None] = (0.0, None)


async def engine_version(host: str, port: int, timeout: float = 5.0) -> str | None:
    """`ClamAV 1.5.4/27801/...` (program and signature database), cached for a few minutes. It is
    recorded with every scan so an audit can tell how current the signatures were."""
    global _version_cache
    cached_at, value = _version_cache
    if time.monotonic() - cached_at < _VERSION_TTL_SECONDS:
        return value
    try:
        reply = await _command(b"zVERSION\x00", host, port, timeout)
    except ScannerUnavailable:
        return None
    value = reply[:100] if reply.startswith("ClamAV") else None
    _version_cache = (time.monotonic(), value)
    return value


def reset_version_cache() -> None:
    global _version_cache
    _version_cache = (0.0, None)
