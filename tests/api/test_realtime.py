"""B4-2: realtime gateway. ASGITransport buffers a whole response, so SSE cannot be read through
it; these tests run uvicorn inside the test's own event loop (same engine, no threads) and read
the stream over a real socket. Writers use the usual in-process client."""

import asyncio
import json
import socket
from collections.abc import AsyncGenerator
from datetime import timedelta
from typing import Any

import httpx
import pytest
import uvicorn
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api import realtime as rt_api
from app.core import realtime as rt
from app.main import app
from app.models.realtime import RealtimeEvent
from app.services import realtime_service
from tests.api.conftest import ClientFor, add_to_project_org
from tests.api.test_data_import import project_with_contact, upload


@pytest.fixture
async def live(session_factory: async_sessionmaker[AsyncSession]) -> AsyncGenerator[str, None]:
    rt_api.reset_state()
    app.dependency_overrides[rt_api.stream_sessions] = lambda: session_factory
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off", timeout_graceful_shutdown=2)
    )
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.05)
    assert server.started
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await asyncio.wait_for(task, 10)
    app.dependency_overrides.pop(rt_api.stream_sessions, None)
    rt_api.reset_state()


class Sse:
    """One live stream, read in a background task into `frames` (parsed) and `comments`."""

    def __init__(self, base: str, pid: str, who: AsyncClient, last: int | str | None = None) -> None:
        self.url = f"{base}/projects/{pid}/events/stream"
        self.headers = dict(who.headers)
        if last is not None:
            self.headers["Last-Event-ID"] = str(last)
        self.frames: list[dict[str, Any]] = []
        self.comments: list[str] = []
        self.status = 0
        self.body = ""
        self._opened = asyncio.Event()
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        async with httpx.AsyncClient(timeout=None) as c:
            async with c.stream("GET", self.url, headers=self.headers) as r:
                self.status = r.status_code
                if r.status_code != 200:
                    self.body = (await r.aread()).decode()
                    self.headers_back = dict(r.headers)
                    self._opened.set()
                    return
                cur: dict[str, Any] = {}
                async for line in r.aiter_lines():
                    if line.startswith(":"):
                        self.comments.append(line[2:])
                        self._opened.set()
                    elif line == "":
                        if cur:
                            self.frames.append(cur)
                        cur = {}
                    else:
                        k, _, v = line.partition(": ")
                        cur[k] = json.loads(v) if k == "data" else v

    async def opened(self) -> "Sse":
        await asyncio.wait_for(self._opened.wait(), 5)
        return self

    async def wait(self, pred: Any, timeout: float = 4.0) -> None:
        async def poll() -> None:
            while not pred(self):
                await asyncio.sleep(0.05)

        await asyncio.wait_for(poll(), timeout)

    def of_type(self, type_: str) -> list[dict[str, Any]]:
        return [f for f in self.frames if f.get("event") == type_]

    async def close(self) -> None:
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):
            pass


async def commit_import(client: AsyncClient, pid: str, n: int) -> None:
    csv = f"Full Name,Email,Age\nP{n},p{n}@x.io,{20 + n}\n".encode()
    prev = (await upload(client, pid, csv)).json()
    r = await client.post(f"/projects/{pid}/imports/{prev['batch_id']}/commit")
    assert r.status_code == 200, r.text


async def shared_project(client: AsyncClient, client_for: ClientFor) -> tuple[str, AsyncClient]:
    pid = await project_with_contact(client)
    await add_to_project_org(pid, "b@example.com")
    b = await client_for("b@example.com")
    await add_to_project_org(pid, "b@example.com")
    r = await client.post(f"/projects/{pid}/members", json={"email": "b@example.com", "role": "viewer"})
    assert r.status_code == 201, r.text
    return pid, b


async def test_write_by_a_is_seen_by_b_quickly_and_slot_is_released(
    client: AsyncClient, client_for: ClientFor, live: str
) -> None:
    pid, b = await shared_project(client, client_for)
    sa = await Sse(live, pid, client).opened()
    sb = await Sse(live, pid, b).opened()
    await commit_import(client, pid, 1)
    await sa.wait(lambda s: s.of_type("import.committed"), 2)
    await sb.wait(lambda s: s.of_type("import.committed"), 2)
    ev = sb.of_type("import.committed")[0]
    assert ev["data"]["project_id"] == pid and ev["data"]["topic"] == "imports"
    assert ev["data"]["data"]["created"] == 1 and "p1@x.io" not in json.dumps(ev)
    assert int(ev["id"]) == ev["data"]["id"]
    await sb.close()
    await sa.close()
    for _ in range(40):  # disconnect frees the per-user slots
        if rt_api._limiter.open_count(str(b.user.id)) == 0:  # type: ignore[attr-defined]
            break
        await asyncio.sleep(0.1)
    assert rt_api._limiter.open_count(str(b.user.id)) == 0  # type: ignore[attr-defined]


async def test_spec_change_is_published(client: AsyncClient, client_for: ClientFor, live: str) -> None:
    pid = await project_with_contact(client)
    s = await Sse(live, pid, client).opened()
    r = await client.post(
        f"/projects/{pid}/spec/ops",
        json={"op_type": "add_field", "payload": {"entity": "Contact", "field": {"name": "city", "type": "string"}}},
    )
    assert r.status_code == 201, r.text
    await s.wait(lambda x: x.of_type("spec.changed"), 3)
    d = s.of_type("spec.changed")[0]["data"]["data"]
    assert d["op_type"] == "add_field" and d["seq"] >= 1
    await s.close()


async def test_resume_with_last_event_id_replays_exactly_the_missed_events(
    client: AsyncClient, client_for: ClientFor, live: str
) -> None:
    pid, b = await shared_project(client, client_for)
    sb = await Sse(live, pid, b).opened()
    await commit_import(client, pid, 1)
    await sb.wait(lambda s: s.of_type("import.committed"))
    last = int(sb.of_type("import.committed")[0]["id"])
    await sb.close()  # B drops
    for n in (2, 3, 4):
        await commit_import(client, pid, n)
    again = await Sse(live, pid, b, last=last).opened()
    await again.wait(lambda s: len(s.of_type("import.committed")) >= 3)
    await asyncio.sleep(1.2)  # nothing more arrives, no duplicates, no resync
    got = [int(f["id"]) for f in again.frames if "id" in f]
    assert len(got) == 3 and got == sorted(set(got)) and min(got) > last
    assert not again.of_type("resync")
    assert [f["data"]["data"]["entity"] for f in again.of_type("import.committed")] == ["Contact"] * 3
    # the query-string form is equivalent
    third = await Sse(live, pid, b, last=got[0]).opened()  # header form again, from the middle
    await third.wait(lambda s: len(s.of_type("import.committed")) >= 2)
    await asyncio.sleep(0.8)
    assert [int(f["id"]) for f in third.frames if "id" in f] == got[1:]
    await again.close()
    await third.close()
    async with httpx.AsyncClient(timeout=5) as c:
        url = f"{live}/projects/{pid}/events/stream?last_event_id={got[1]}"
        seen: list[str] = []
        async with c.stream("GET", url, headers=dict(b.headers)) as r:
            async for line in r.aiter_lines():
                if line.startswith("id: "):
                    seen.append(line[4:])
                    break
        assert seen == [str(got[2])]


async def test_other_projects_and_non_members_never_see_events(
    client: AsyncClient, client_for: ClientFor, live: str
) -> None:
    pid, _ = await shared_project(client, client_for)
    eve = await client_for("eve@example.com")
    other = await project_with_contact(eve)
    assert (await eve.get(f"/projects/{pid}/presence")).status_code == 404
    denied = await Sse(live, pid, eve).opened()
    assert denied.status == 404
    mine = await Sse(live, pid, client, last=0).opened()
    theirs = await Sse(live, other, eve).opened()
    await commit_import(eve, other, 1)
    await theirs.wait(lambda s: s.of_type("import.committed"))
    await commit_import(client, pid, 1)
    await mine.wait(lambda s: s.of_type("import.committed"))
    await asyncio.sleep(0.8)
    assert {f["data"]["project_id"] for f in mine.frames if "data" in f} == {pid}
    assert {f["data"]["project_id"] for f in theirs.frames if "data" in f} == {other}
    # replaying from 0 on eve's project cannot reach project pid's rows either
    replay = await Sse(live, other, eve, last=0).opened()
    await replay.wait(lambda s: s.of_type("import.committed"))
    assert {f["data"]["project_id"] for f in replay.frames if "data" in f} == {other}
    # a member of neither project asking for the other's stream with a valid cursor: still 404
    assert (await Sse(live, other, client, last=0).opened()).status == 404
    for s in (mine, theirs, replay):
        await s.close()


async def test_too_many_streams_and_reconnect_throttle(
    client: AsyncClient, live: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = await project_with_contact(client)
    held = [await Sse(live, pid, client).opened() for _ in range(5)]
    assert all(s.status == 200 for s in held)
    sixth = await Sse(live, pid, client).opened()
    assert sixth.status == 429 and json.loads(sixth.body)["code"] == "realtime_too_many_streams"
    for s in held:
        await s.close()
    for _ in range(40):
        if rt_api._limiter.open_count(str(client.user.id)) == 0:  # type: ignore[attr-defined]
            break
        await asyncio.sleep(0.1)
    # reconnect storm: after N connects in the window the next is refused with Retry-After
    monkeypatch.setattr(rt_api, "_reconnects", rt.ReconnectGuard(max_hits=2, window=60))
    for _ in range(2):
        s = await Sse(live, pid, client).opened()
        assert s.status == 200
        await s.close()
        await asyncio.sleep(0.3)
    storm = await Sse(live, pid, client).opened()
    assert storm.status == 429
    assert json.loads(storm.body)["code"] == "realtime_reconnect_throttled"
    assert int(storm.headers_back["retry-after"]) >= 1


async def test_resync_when_cursor_is_older_than_the_retention_floor(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    live: str,
) -> None:
    pid = await project_with_contact(client)
    for n in (1, 2, 3):
        await commit_import(client, pid, n)
    async with session_factory() as s:
        ids = list((await s.execute(select(RealtimeEvent.id).order_by(RealtimeEvent.id))).scalars())
        assert len(ids) >= 4  # one spec.changed + 3 imports
        import uuid as _u

        gone = await realtime_service.prune_events(s, _u.UUID(pid), keep=2)
        await s.commit()
    assert gone == len(ids) - 2
    behind = await Sse(live, pid, client, last=ids[0]).opened()
    await behind.wait(lambda s: s.frames and s.frames[0].get("event") == "resync")
    first = behind.frames[0]
    assert first["event"] == "resync" and int(first["id"]) == ids[-3]
    await behind.wait(lambda s: len(s.frames) >= 3)
    assert [int(f["id"]) for f in behind.frames[1:3]] == ids[-2:]  # the retained tail follows
    # a client that was up to date does not resync; garbage cursors mean "live only"
    fine = await Sse(live, pid, client, last=ids[-1]).opened()
    junk = await Sse(live, pid, client, last="not-a-number").opened()
    await asyncio.sleep(0.8)
    assert not fine.of_type("resync") and not fine.frames and not junk.frames
    for s2 in (behind, fine, junk):
        await s2.close()


async def test_prune_by_age_and_count(client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]) -> None:
    import uuid as _u

    pid = _u.UUID(await project_with_contact(client))
    async with session_factory() as s:
        for i in range(5):
            await realtime_service.publish(s, pid, "t", "x", {"i": i})
        await s.commit()
    async with session_factory() as s:
        assert await realtime_service.prune_events(s, pid, keep=10) == 0
        assert await realtime_service.prune_events(s, pid, keep=10, max_age=timedelta(seconds=-5)) == 6
        floor, head = await realtime_service.floor_and_head(s, pid)
        await s.commit()
    assert floor > 0 and head == 0


async def test_presence_heartbeat_roster_and_keepalive(
    client: AsyncClient, client_for: ClientFor, live: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rt, "HEARTBEAT_SECONDS", 0.4)
    pid, b = await shared_project(client, client_for)
    s = await Sse(live, pid, client).opened()
    r = await b.post(f"/projects/{pid}/presence/heartbeat", json={"where": "import wizard"})
    assert r.status_code == 204  # a viewer may heartbeat
    assert (await b.post(f"/projects/{pid}/presence/heartbeat", json={"where": "x" * 81})).status_code == 422
    roster = (await client.get(f"/projects/{pid}/presence")).json()
    assert [(e["user_id"], e["where"]) for e in roster] == [(str(b.user.id), "import wizard")]  # type: ignore[attr-defined]
    await s.wait(lambda x: x.of_type("presence"))
    users = s.of_type("presence")[0]["data"]["data"]["users"]
    assert users[0]["where"] == "import wizard" and "id" not in s.of_type("presence")[0]
    await s.wait(lambda x: "keepalive" in x.comments)
    await s.close()


async def test_presence_expires_on_the_api_path(
    client: AsyncClient, client_for: ClientFor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WP-A: a client that stops heartbeating drops out of GET /presence once the TTL lapses."""
    from types import SimpleNamespace

    rt_api.reset_state()
    clock = [1000.0]
    monkeypatch.setattr(rt_api, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    pid, b = await shared_project(client, client_for)
    assert (await b.post(f"/projects/{pid}/presence/heartbeat", json={"where": "x"})).status_code == 204
    clock[0] += 10
    assert (await client.post(f"/projects/{pid}/presence/heartbeat", json={"where": "y"})).status_code == 204
    roster = (await client.get(f"/projects/{pid}/presence")).json()
    assert len(roster) == 2
    clock[0] += rt.PresenceBook().ttl - 5  # b is now past its TTL, the owner is not
    roster = (await client.get(f"/projects/{pid}/presence")).json()
    assert [e["where"] for e in roster] == ["y"]
    clock[0] += 1000  # everyone gone: empty roster, no leftover book
    assert (await client.get(f"/projects/{pid}/presence")).json() == []
    assert pid not in {str(k) for k in rt_api._books}
    rt_api.reset_state()
