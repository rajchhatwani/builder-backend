"""Realtime protocol (generated): the event envelope, Server-Sent-Events frames, `Last-Event-ID` parsing, the
stale-cursor rule, the per-user stream cap and the reconnect throttle. Pure: no I/O, clocks are injected.

An event names a record, never its content: `data` is {entity, record_id, op}. Nothing a caller may not
read can travel in a frame."""

import json
import os
import time
from collections import defaultdict, deque
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from datetime import datetime
from typing import Any


def _env_number(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


MAX_STREAMS_PER_USER = int(_env_number("REALTIME_MAX_STREAMS_PER_USER", 5))
RECONNECT_MAX = int(_env_number("REALTIME_RECONNECT_MAX", 20))
RECONNECT_WINDOW_SECONDS = 60.0
HEARTBEAT_SECONDS = 15.0
MAX_STREAM_SECONDS = _env_number("REALTIME_MAX_STREAM_SECONDS", 300.0)
POLL_SECONDS = _env_number("REALTIME_POLL_SECONDS", 0.5)
IDLE_POLL_SECONDS = max(POLL_SECONDS, _env_number("REALTIME_IDLE_POLL_SECONDS", 1.0))  # the idle backoff stops here
MAX_STREAMS_TOTAL = int(_env_number("REALTIME_MAX_STREAMS", 50))  # per process, all people together
RETENTION_HOURS = 24
RETENTION_MAX_EVENTS = 10_000
MAX_EVENT_ID = 2**63 - 1

TOO_MANY_STREAMS = "realtime_too_many_streams"
STREAMS_AT_CAPACITY = "realtime_at_capacity"
RECONNECT_THROTTLED = "realtime_reconnect_throttled"


@dataclass(frozen=True)
class Event:
    """id is the table's BIGSERIAL (ordering and resume cursor); a `resync` frame carries the new cursor."""

    topic: str
    type: str
    data: dict[str, Any]
    at: datetime
    id: int | None = None

    def envelope(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "topic": self.topic,
            "type": self.type,
            "data": self.data,
            "at": self.at.isoformat(),
        }


def _single_line(text: str) -> str:
    return text.replace("\r", " ").replace("\n", " ")


def encode_event(event: Event) -> bytes:
    """One SSE frame. `data` is single-line JSON; `id:` is left out when the event has none."""
    lines = []
    if event.id is not None:
        lines.append(f"id: {event.id}")
    lines.append(f"event: {_single_line(event.type)}")
    lines.append("data: " + json.dumps(event.envelope(), separators=(",", ":"), default=str))
    return ("\n".join(lines) + "\n\n").encode()


def encode_comment(text: str = "keepalive") -> bytes:
    return f": {_single_line(text)}\n\n".encode()


def parse_last_event_id(value: str | None) -> int | None:
    """A cursor from the header or `?last_event_id=`; anything that is not a plain non-negative integer
    in range is garbage and means "no cursor"."""
    if value is None:
        return None
    text = value.strip()
    if not text or len(text) > 19 or not text.isascii() or not text.isdigit():
        return None
    number = int(text)
    return number if number <= MAX_EVENT_ID else None


def needs_resync(last_id: int, floor_id: int, head_id: int) -> bool:
    """True when the client's cursor cannot be replayed exactly: events at or below `floor_id` were pruned
    and the client had not seen them all, or the cursor is ahead of anything this app ever had."""
    return last_id < floor_id or last_id > max(floor_id, head_id)


class ConnectionLimiter:
    """Concurrent streams per user and in all (in this process). `acquire` is all-or-nothing; `release` is
    idempotent. A stream polls the database, so the total keeps the streams from using up the connection pool."""

    def __init__(self, max_per_user: int = MAX_STREAMS_PER_USER, max_total: int = MAX_STREAMS_TOTAL) -> None:
        self.max = max_per_user
        self.max_total = max_total
        self._open: dict[str, int] = defaultdict(int)

    def total(self) -> int:
        return sum(self._open.values())

    def at_capacity(self) -> bool:
        return self.total() >= self.max_total

    def acquire(self, user: str) -> bool:
        if self._open[user] >= self.max:
            return False
        self._open[user] += 1
        return True

    def release(self, user: str) -> None:
        if self._open.get(user, 0) <= 1:
            self._open.pop(user, None)
        else:
            self._open[user] -= 1

    def open_count(self, user: str) -> int:
        return self._open.get(user, 0)


class ReconnectGuard:
    """A client that opens more than `max_hits` streams in `window` seconds (per key) is refused until its
    oldest hit leaves the window. Refused attempts are not recorded."""

    def __init__(
        self,
        max_hits: int = RECONNECT_MAX,
        window: float = RECONNECT_WINDOW_SECONDS,
        clock: Callable[[], float] | None = None,
        max_keys: int = 20_000,
    ) -> None:
        self.max_hits = max_hits
        self.window = window
        self._clock = clock or time.monotonic
        self._max_keys = max_keys
        self._hits: dict[Hashable, deque[float]] = {}

    def check(self, key: Hashable) -> int | None:
        """Record a connect. None = allowed; an int = refused, retry after that many seconds."""
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.window:
            hits.popleft()
        if len(hits) >= self.max_hits:
            return max(1, int(self.window - (now - hits[0])) + 1)
        hits.append(now)
        if len(self._hits) > self._max_keys:
            for k in [k for k, h in self._hits.items() if not h or now - h[-1] >= self.window]:
                del self._hits[k]
        return None
