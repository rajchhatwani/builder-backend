"""Realtime gateway primitives (B4-2, C18). Pure: no I/O, clocks are injected.

The platform streams project events (Server-Sent Events) to builder clients. This module holds
what can be tested without a server: the event envelope, the SSE frame encoder, `Last-Event-ID`
parsing, the presence roster, the per-user stream cap and the reconnect throttle. Generated apps
get realtime in a later generator work package; nothing here ships inside a generated app.
"""

import json
from collections import defaultdict, deque
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

MAX_STREAMS_PER_USER = 5
RECONNECT_MAX = 20
RECONNECT_WINDOW_SECONDS = 60.0
PRESENCE_TTL_SECONDS = 30.0
HEARTBEAT_SECONDS = 15.0
RETENTION_HOURS = 24
RETENTION_MAX_EVENTS = 10_000
MAX_EVENT_ID = 2**63 - 1

TOO_MANY_STREAMS = "realtime_too_many_streams"
RECONNECT_THROTTLED = "realtime_reconnect_throttled"


@dataclass(frozen=True)
class Event:
    """id is the table's BIGSERIAL (ordering and resume cursor); presence events have no id."""

    project_id: str
    topic: str
    type: str
    data: dict[str, Any]
    at: datetime
    id: int | None = None

    def envelope(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "topic": self.topic,
            "type": self.type,
            "data": self.data,
            "at": self.at.isoformat(),
        }


def _single_line(text: str) -> str:
    return text.replace("\r", " ").replace("\n", " ")


def encode_event(event: Event) -> bytes:
    """One SSE frame. `data` is single-line JSON (json.dumps never emits a raw newline);
    `id:` is left out when the event has none, so presence events never move the cursor."""
    lines = []
    if event.id is not None:
        lines.append(f"id: {event.id}")
    lines.append(f"event: {_single_line(event.type)}")
    lines.append("data: " + json.dumps(event.envelope(), separators=(",", ":"), default=str))
    return ("\n".join(lines) + "\n\n").encode()


def encode_comment(text: str = "keepalive") -> bytes:
    return f": {_single_line(text)}\n\n".encode()


def parse_last_event_id(value: str | None) -> int | None:
    """A cursor from the header or `?last_event_id=`; anything that is not a plain
    non-negative integer in range is garbage and means "no cursor"."""
    if value is None:
        return None
    text = value.strip()
    if not text or len(text) > 19 or not text.isascii() or not text.isdigit():
        return None
    number = int(text)
    return number if number <= MAX_EVENT_ID else None


def needs_resync(last_id: int, floor_id: int, head_id: int) -> bool:
    """True when the client's cursor cannot be replayed exactly: events at or below `floor_id`
    were pruned and the client had not seen them all, or the cursor is ahead of anything this
    project ever had (a stale cursor from another database)."""
    return last_id < floor_id or last_id > max(floor_id, head_id)


@dataclass
class PresenceEntry:
    user_id: str
    display: str
    where: str
    last_seen: float


@dataclass
class PresenceBook:
    """Who is looking at one project right now. Entries lapse `ttl` seconds after their last touch."""

    ttl: float = PRESENCE_TTL_SECONDS
    _entries: dict[str, PresenceEntry] = field(default_factory=dict)

    def touch(self, user: str, now: float, where: str = "", display: str = "") -> None:
        self._entries[user] = PresenceEntry(user, display or user, where, now)

    def expire(self, now: float, ttl: float | None = None) -> int:
        limit = self.ttl if ttl is None else ttl
        gone = [u for u, e in self._entries.items() if now - e.last_seen > limit]
        for u in gone:
            del self._entries[u]
        return len(gone)

    def snapshot(self, now: float) -> list[PresenceEntry]:
        self.expire(now)
        return sorted(self._entries.values(), key=lambda e: (e.display, e.user_id))

    def __len__(self) -> int:
        return len(self._entries)


class ConnectionLimiter:
    """Concurrent streams per user. `acquire` is all-or-nothing; `release` is idempotent per slot."""

    def __init__(self, max_per_user: int = MAX_STREAMS_PER_USER) -> None:
        self.max = max_per_user
        self._open: dict[str, int] = defaultdict(int)

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
    """A client that opens more than `max_hits` streams in `window` seconds (per key) is
    refused until its oldest hit leaves the window. Refused attempts are not recorded."""

    def __init__(
        self,
        max_hits: int = RECONNECT_MAX,
        window: float = RECONNECT_WINDOW_SECONDS,
        clock: Callable[[], float] | None = None,
        max_keys: int = 20_000,
    ) -> None:
        import time

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
