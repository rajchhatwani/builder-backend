"""A stand-in for ClamAV's clamd (generated): a real TCP server that speaks the INSTREAM protocol.

The tests run the real scanner client (app/storage/clamav.py) against it, so the framing, the replies
and the failure handling are exercised over an actual socket. It "detects" a harmless marker string
(never a real virus signature, so nothing in this project trips an antivirus), and it can be told to
misbehave the ways a real daemon does.
"""

import socketserver
import struct
import threading

# Any upload containing this text is reported as infected by the stand-in.
MARKER = b"FAKE-MALWARE-" + b"TEST-MARKER"
SIGNATURE = "Test.Fake.Malware"
VERSION = "ClamAV 1.5.4-fake/1/Mon Jan  1 00:00:00 2026"


class _Handler(socketserver.BaseRequestHandler):
    server: "FakeClamd"

    def _read_exact(self, size: int) -> bytes | None:
        data = b""
        while len(data) < size:
            piece = self.request.recv(size - len(data))
            if not piece:
                return None
            data += piece
        return data

    def _read_command(self) -> bytes | None:
        command = b""
        while not command.endswith(b"\x00"):
            piece = self.request.recv(1)
            if not piece:
                return None
            command += piece
        return command

    def handle(self) -> None:
        command = self._read_command()
        fake = self.server
        fake.commands.append(command or b"")
        mode = fake.mode
        if command == b"zPING\x00":
            self.request.sendall(b"PONG\x00")
        elif command == b"zVERSION\x00":
            self.request.sendall(VERSION.encode() + b"\x00")
        elif command == b"zINSTREAM\x00":
            self._instream(mode)

    def _instream(self, mode: str) -> None:
        fake = self.server
        if mode == "hang":
            threading.Event().wait(30)
            return
        if mode == "close":
            return  # accept, then hang up without a word
        received = b""
        while True:
            header = self._read_exact(4)
            if header is None:
                fake.framing_errors += 1
                return
            (length,) = struct.unpack("!I", header)
            if length == 0:
                break
            chunk = self._read_exact(length)
            if chunk is None:
                fake.framing_errors += 1
                return
            received += chunk
            if len(received) > fake.stream_max_length:
                self.request.sendall(b"INSTREAM size limit exceeded. ERROR\x00")
                return
        fake.scanned.append(received)
        if mode == "error":
            reply = b"stream: lstat() failed. ERROR\x00"
        elif mode == "garbage":
            reply = b"hello there\x00"
        elif mode == "unknown":
            reply = b"stream: OK but not really\x00"
        elif MARKER in received:
            reply = f"stream: {SIGNATURE} FOUND\x00".encode()
        else:
            reply = b"stream: OK\x00"
        self.request.sendall(reply)


class FakeClamd(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.mode = "normal"  # normal | error | garbage | unknown | hang | close
        self.stream_max_length = 10**9
        self.scanned: list[bytes] = []  # what each INSTREAM carried, in order
        self.commands: list[bytes] = []
        self.framing_errors = 0
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    def start(self) -> "FakeClamd":
        self._thread.start()
        return self

    def stop(self) -> None:
        self.shutdown()
        self.server_close()

    def reset(self) -> None:
        self.mode = "normal"
        self.stream_max_length = 10**9
        self.scanned.clear()
        self.commands.clear()
        self.framing_errors = 0
