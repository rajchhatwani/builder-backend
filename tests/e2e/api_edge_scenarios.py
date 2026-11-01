"""Scenario tests for the generated `api_edge_orders` project. Copied into the project's tests/ folder by
tests/e2e/test_api_edge_stack.py and run against a real Postgres, talking to REAL uvicorn processes over
HTTP (two of them at once, so the rules are proven across API processes, not just inside one).

Rules under test: an after_commit hook runs once, after the real commit, never on a replay or a failed request; ten and more parallel requests with one Idempotency-Key write exactly once, across two
processes; a server killed with SIGKILL in the middle of a keyed write leaves no half state and the retry
runs once; a key of one tenant never replays into another; a token bucket is shared by every API process;
an old API version keeps its old response shape over the wire.
"""

import asyncio
import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from tests._auth_support import outbox, sign_in  # noqa: F401

from app.db import session_factory
from app.main import app
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def servers(outbox) -> Iterator[Callable[..., list[str]]]:  # noqa: ANN001, F811
    started: list[subprocess.Popen[bytes]] = []

    def start(count: int = 2, **env: str) -> list[str]:
        urls = []
        for _ in range(count):
            port = free_port()
            process = subprocess.Popen(
                [sys.executable, "edge_server.py", str(port)],
                cwd=ROOT, env={**os.environ, **env}, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            started.append(process)
            urls.append(f"http://127.0.0.1:{port}")
        deadline = time.monotonic() + 60
        for url, process in zip(urls, started[-count:], strict=True):
            while True:
                try:
                    if httpx.get(url + "/health", timeout=2).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                assert process.poll() is None and time.monotonic() < deadline, (process.stderr.read() if process.stderr else b"")
                time.sleep(0.2)
        return urls

    yield start
    for process in started:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=30)
        if process.stderr:
            process.stderr.close()


@pytest.fixture
async def users() -> dict[str, dict[str, str]]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        return {
            "a": await sign_in(http, "a-admin@example.com", roles=["admin"], n=0),
            "b": await sign_in(http, "b-admin@example.com", roles=["admin"], n=1),
        }


async def count(table: str) -> int:
    async with session_factory() as session:
        return int((await session.execute(sa.text(f"SELECT count(*) FROM {table}"))).scalar_one())


def body(name: str) -> dict[str, str]:
    return {"name": name}


async def test_parallel_requests_with_one_key_across_two_processes_write_once(servers, users) -> None:  # noqa: ANN001
    urls = servers(2)
    headers = {**users["a"], "Idempotency-Key": "parallel-across-procs-1"}
    async with httpx.AsyncClient(timeout=60) as http:
        calls = [http.post(urls[i % 2] + "/customers", json=body("Once"), headers=headers) for i in range(24)]
        responses = await asyncio.gather(*calls)
        codes = sorted(r.status_code for r in responses)
        assert set(codes) <= {201, 409}, codes
        assert 201 in codes
        winners = {r.json()["id"] for r in responses if r.status_code == 201}
        assert len(winners) == 1  # everyone who got a 201 got the same record
        assert await count("customers") == 1
        assert await count("api_idempotency") == 1
        replay = await http.post(urls[1] + "/customers", json=body("Once"), headers=headers)
        assert replay.status_code == 201 and replay.headers["Idempotent-Replayed"] == "true"
        assert replay.json()["id"] in winners
        different = await http.post(urls[0] + "/customers", json=body("Other"), headers=headers)
        assert different.status_code == 422 and different.json()["code"] == "idempotency_key_reused"
        assert await count("customers") == 1


async def test_distinct_keys_in_parallel_all_write(servers, users) -> None:  # noqa: ANN001
    urls = servers(2)
    async with httpx.AsyncClient(timeout=60) as http:
        calls = [
            http.post(urls[i % 2] + "/customers", json=body(f"C{i}"), headers={**users["a"], "Idempotency-Key": f"distinct-key-{i:04d}"})
            for i in range(16)
        ]
        responses = await asyncio.gather(*calls)
    assert [r.status_code for r in responses] == [201] * 16
    assert await count("customers") == 16
    assert await count("api_idempotency") == 16


async def test_a_key_of_one_tenant_never_replays_into_another(servers, users) -> None:  # noqa: ANN001
    urls = servers(2)
    key = {"Idempotency-Key": "shared-by-two-tenants"}
    async with httpx.AsyncClient(timeout=60) as http:
        first, second = await asyncio.gather(
            http.post(urls[0] + "/customers", json=body("Same body"), headers={**users["a"], **key}),
            http.post(urls[1] + "/customers", json=body("Same body"), headers={**users["b"], **key}),
        )
        assert first.status_code == second.status_code == 201
        assert first.json()["id"] != second.json()["id"]
        again = await http.post(urls[1] + "/customers", json=body("Same body"), headers={**users["a"], **key})
        assert again.headers["Idempotent-Replayed"] == "true" and again.json()["id"] == first.json()["id"]
    assert await count("customers") == 2
    async with session_factory() as session:
        scopes = (await session.execute(sa.text("SELECT DISTINCT tenant_key FROM api_idempotency"))).all()
    assert len(scopes) == 2


async def test_a_server_killed_mid_write_leaves_no_half_state_and_the_retry_runs_once(servers, users) -> None:  # noqa: ANN001
    urls = servers(2, EDGE_WRITE_DELAY="3")
    headers = {**users["a"], "Idempotency-Key": "killed-mid-write-1"}
    async with httpx.AsyncClient(timeout=60) as http:
        inflight = asyncio.create_task(http.post(urls[0] + "/customers", json=body("Crash"), headers=headers))
        await asyncio.sleep(1.5)  # the write is running (and sleeping in a hook) inside its transaction
        assert await count("customers") == 0  # nothing is visible before the commit
        os.kill(_pid_of(urls[0]), 9)
        with pytest.raises(httpx.HTTPError):
            await inflight
        assert await count("customers") == 0
        deadline = time.monotonic() + 40
        while True:
            retry = await http.post(urls[1] + "/customers", json=body("Crash"), headers=headers)
            if retry.status_code == 201 or time.monotonic() > deadline:
                break
            assert retry.status_code == 409, retry.text  # only 'still in progress' while Postgres drops the dead session
            await asyncio.sleep(0.5)
        assert retry.status_code == 201, retry.text
        assert "idempotent-replayed" not in retry.headers  # it ran for real: the first one never committed
        assert await count("customers") == 1
        assert await count("api_idempotency") == 1


def _pid_of(url: str) -> int:
    """The process listening on this port (found through /proc, no extra dependency)."""
    port = int(url.rsplit(":", 1)[1])
    inode = None
    for line in Path("/proc/net/tcp").read_text().splitlines()[1:]:
        fields = line.split()
        if fields[3] == "0A" and int(fields[1].split(":")[1], 16) == port:
            inode = fields[9]
    assert inode is not None, "server not listening"
    for proc in Path("/proc").iterdir():
        if proc.name.isdigit():
            try:
                for fd in (proc / "fd").iterdir():
                    if os.readlink(fd) == f"socket:[{inode}]":
                        return int(proc.name)
            except OSError:
                continue
    raise AssertionError("no process owns the socket")


async def test_a_bucket_is_shared_by_every_api_process(servers, users) -> None:  # noqa: ANN001
    urls = servers(2, EDGE_USER_CAPACITY="10", EDGE_USER_REFILL="0.05")
    async with httpx.AsyncClient(timeout=60) as http:
        calls = [http.get(urls[i % 2] + "/auth/me", headers=users["a"]) for i in range(40)]
        responses = await asyncio.gather(*calls)
        ok = [r for r in responses if r.status_code == 200]
        refused = [r for r in responses if r.status_code == 429]
        assert len(ok) + len(refused) == 40
        assert 10 <= len(ok) <= 12, len(ok)  # capacity 10, a trickle of refill; NOT 20 (one bucket per process)
        assert all(int(r.headers["Retry-After"]) >= 1 and r.headers["RateLimit-Remaining"] == "0" for r in refused)
        assert refused[0].json()["code"] == "rate_limited"
        other_user = await http.get(urls[0] + "/auth/me", headers=users["b"])
        assert other_user.status_code == 200  # another caller has a bucket of their own


async def test_an_old_api_version_keeps_its_old_shape_over_the_wire(servers, users) -> None:  # noqa: ANN001
    urls = servers(1)
    async with httpx.AsyncClient(timeout=60) as http:
        created = await http.post(urls[0] + "/customers", json=body("Shape"), headers={**users["a"], "API-Version": "2026-11-01"})
        old = await http.post(urls[0] + "/customers", json=body("Shape"), headers={**users["a"], "API-Version": "2026-01-15"})
        assert created.status_code == old.status_code == 201
        assert "id" in created.json() and "legacy_id" not in created.json()
        assert "legacy_id" in old.json() and "id" not in old.json()
        assert old.headers["API-Version"] == "2026-01-15" and created.headers["API-Version"] == "2026-11-01"
        listed = await http.get(urls[0] + "/customers", headers={**users["a"], "API-Version": "2026-01-15"})
        assert all("legacy_id" in item for item in listed.json()["items"])
        unknown = await http.get(urls[0] + "/customers", headers={**users["a"], "API-Version": "2030-01-01"})
        assert unknown.status_code == 400 and unknown.json()["code"] == "unsupported_api_version"
        log = (await http.get(urls[0] + "/api-versions")).json()
        assert log["latest"] == "2026-11-01" and [v["date"] for v in log["versions"]][0] == "2026-11-01"


async def test_after_commit_runs_once_after_the_commit_and_never_for_a_failed_or_replayed_request(servers, users, tmp_path) -> None:  # noqa: ANN001
    marker = tmp_path / "after_commit.log"
    urls = servers(2, EDGE_MARKER_FILE=str(marker))

    def seen() -> list[str]:
        return marker.read_text().split() if marker.exists() else []

    async with httpx.AsyncClient(timeout=60) as http:
        # a failed keyed request (validation) and a keyed request that is refused: nothing runs
        bad = await http.post(urls[0] + "/customers", json={"nope": 1}, headers={**users["a"], "Idempotency-Key": "ac-bad-key-0001"})
        assert bad.status_code in (400, 422)
        assert seen() == [] and await count("customers") == 0
        # 16 parallel requests with one key across two processes: one write, the hook ran exactly once
        headers = {**users["a"], "Idempotency-Key": "ac-parallel-key-1"}
        responses = await asyncio.gather(*[http.post(urls[i % 2] + "/customers", json=body("Hooked"), headers=headers) for i in range(16)])
        assert 201 in {r.status_code for r in responses} and set(r.status_code for r in responses) <= {201, 409}
        assert await count("customers") == 1
        assert seen() == ["1"]  # once, and the row was already visible to a second connection
        replay = await http.post(urls[1] + "/customers", json=body("Hooked"), headers=headers)
        assert replay.headers["Idempotent-Replayed"] == "true"
        assert seen() == ["1"]  # no second run for a replay
        # the same key for a different request is refused: still nothing new
        other = await http.post(urls[0] + "/customers", json=body("Different"), headers=headers)
        assert other.status_code == 422
        assert seen() == ["1"] and await count("customers") == 1
