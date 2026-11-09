"""B4-2: the pure realtime pieces (frames, cursor, presence, limits) with injected clocks."""

import json
from datetime import UTC, datetime

from app.core import realtime as rt

AT = datetime(2026, 11, 9, tzinfo=UTC)


def test_frame_encoding_is_single_line_json() -> None:
    ev = rt.Event("p1", "imports", "import.committed", {"note": "a\nb", "n": 2}, AT, 41)
    frame = rt.encode_event(ev).decode()
    lines = frame.split("\n")
    assert lines[0] == "id: 41" and lines[1] == "event: import.committed"
    assert lines[2].startswith("data: ") and frame.endswith("\n\n") and len(lines) == 5
    env = json.loads(lines[2][6:])
    assert env == {
        "id": 41,
        "project_id": "p1",
        "topic": "imports",
        "type": "import.committed",
        "data": {"note": "a\nb", "n": 2},
        "at": AT.isoformat(),
    }


def test_event_without_id_has_no_id_line_and_comments_are_comments() -> None:
    frame = rt.encode_event(rt.Event("p", "presence", "presence", {}, AT)).decode()
    assert "id:" not in frame and frame.startswith("event: presence\n")
    assert rt.encode_comment("keep\nalive") == b": keep alive\n\n"


def test_parse_last_event_id() -> None:
    assert rt.parse_last_event_id("17") == 17
    assert rt.parse_last_event_id(" 0 ") == 0
    for bad in (None, "", "abc", "-1", "1.5", "1e3", "12 13", "٣", str(2**63), "9" * 40):
        assert rt.parse_last_event_id(bad) is None, bad
    assert rt.parse_last_event_id(str(2**63 - 1)) == 2**63 - 1


def test_presence_expires_with_injected_clock() -> None:
    book = rt.PresenceBook(ttl=30)
    book.touch("a", 100.0, "editor", "Ann")
    book.touch("b", 110.0, "", "")
    assert [e.user_id for e in book.snapshot(120.0)] == ["a", "b"]
    assert [e.user_id for e in book.snapshot(131.0)] == ["b"]  # a lapsed (31 s)
    book.touch("a", 135.0, "import", "Ann")  # a touch revives and updates where
    assert {e.user_id: e.where for e in book.snapshot(136.0)} == {"a": "import", "b": ""}
    assert book.expire(500.0) == 2 and len(book) == 0


def test_connection_limiter_caps_and_releases() -> None:
    lim = rt.ConnectionLimiter()
    assert all(lim.acquire("u") for _ in range(5))
    assert not lim.acquire("u") and lim.acquire("other")
    lim.release("u")
    assert lim.acquire("u") and not lim.acquire("u")
    for _ in range(20):
        lim.release("u")  # extra releases never go negative
    assert lim.open_count("u") == 0 and lim.acquire("u")


def test_reconnect_throttle_sliding_window() -> None:
    now = [0.0]
    guard = rt.ReconnectGuard(clock=lambda: now[0])
    for i in range(20):
        now[0] = i  # 20 connects in 20 s are fine
        assert guard.check(("u", "p")) is None
    now[0] = 21
    retry = guard.check(("u", "p"))
    assert retry is not None and 1 <= retry <= 60
    assert guard.check(("v", "p")) is None and guard.check(("u", "q")) is None  # per user+project
    now[0] = 60  # first hit (t=0) left the window
    assert guard.check(("u", "p")) is None
    assert guard.check(("u", "p")) is not None


def test_retention_floor_decides_resync() -> None:
    assert not rt.needs_resync(10, 0, 50)  # nothing pruned
    assert not rt.needs_resync(30, 30, 50)  # saw everything pruned
    assert rt.needs_resync(29, 30, 50)  # events <= 30 are gone and we missed some
    assert rt.needs_resync(900, 30, 50)  # cursor from the future
    assert not rt.needs_resync(50, 30, 50)
