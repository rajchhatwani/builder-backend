"""B3-10: a real preview under gVisor (runsc). Needs Docker, the runsc runtime and the
`bb-preview-app:1` image (docker build -t bb-preview-app:1 docker/preview-app).

One project (small neutral spec with a seed profile) is previewed end to end: seeded data through
the host proxy with and without the token, no egress from inside the stack, sleep, wake on
request, and expiry that removes containers, network and code.
"""

import asyncio
import shutil
import subprocess
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from app.config import Settings
from app.main import app
from app.models.preview import Preview
from app.services import preview_service as ps
from app.services.sandbox import DockerSandbox
from tests.api.conftest import (  # noqa: F401  (fixtures used by name)
    _clean_tables,
    _fast_hashing_and_fresh_limiter,
    _no_dev_rls,
    _secret_key,
    _unlimited_personal_plan,
    client,
    client_for,
    database_url,
    engine,
    make_user,
    override_session,
    session_factory,
)

TOKEN = "X-Preview-Token"
SPEC = {
    "spec_version": 1,
    "project": {"name": "Pet Shop", "slug": "pet-shop", "description": None, "db_engine": "postgres"},
    "entities": [
        {
            "name": "Pet", "table_name": "pets", "plural_path": "pets", "options": {},
            "fields": [
                {"name": "name", "type": "string", "required": True, "max_length": 80},
                {"name": "age", "type": "integer", "min_value": 0},
            ],
        }
    ],
    "relations": [],
    "seed": [
        {
            "name": "demo", "seed": 7, "as_of": "2026-10-01",
            "entities": [
                {
                    "entity": "Pet", "count": 6,
                    "fields": [
                        {"field": "name", "generator": {"type": "words", "min_words": 1, "max_words": 2}},
                        {"field": "age", "generator": {"type": "int_range", "min": 1, "max": 15}},
                    ],
                }
            ],
        }
    ],
}  # fmt: skip


def _docker_ok() -> bool:
    if shutil.which("docker") is None:
        return False
    info = subprocess.run(
        ["docker", "info", "--format", "{{json .Runtimes}}"], capture_output=True, text=True
    )
    img = subprocess.run(["docker", "image", "inspect", "bb-preview-app:1"], capture_output=True)
    return info.returncode == 0 and "runsc" in info.stdout and img.returncode == 0


pytestmark = pytest.mark.skipif(
    not _docker_ok(), reason="needs docker + runsc + the bb-preview-app:1 image"
)


def _containers() -> list[str]:
    out = subprocess.run(
        ["docker", "ps", "-a", "--filter", "label=bb.sandbox=1", "--format", "{{.Names}}"],
        capture_output=True, text=True,
    )  # fmt: skip
    return out.stdout.split()


def _networks() -> list[str]:
    out = subprocess.run(
        ["docker", "network", "ls", "--filter", "label=bb.sandbox=1", "--format", "{{.Name}}"],
        capture_output=True, text=True,
    )  # fmt: skip
    return out.stdout.split()


@pytest.fixture
async def runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, session_factory  # noqa: F811
) -> AsyncIterator[Settings]:
    settings = Settings(
        environment="test", sandbox_runtime="runsc", preview_root=str(tmp_path / "pv"),
        preview_wake_timeout_seconds=120, preview_lazy_sweep=False,
    )  # fmt: skip
    from app.api import previews as api

    monkeypatch.setattr(ps, "get_settings", lambda: settings)
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    monkeypatch.setattr(ps, "session_factory", lambda: session_factory)
    yield settings
    for t in list(ps._tasks):
        t.cancel()
    await asyncio.gather(*ps._tasks, return_exceptions=True)
    await DockerSandbox(settings).reap(now=time.time() + 10**7)  # whatever a failure left behind


async def _wait(c: AsyncClient, url: str, want: str, timeout: float = 150) -> dict[str, object]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        body = (await c.get(url)).json()
        if body["state"] == want:
            out: dict[str, object] = body
            return out
        if body["state"] == "failed":
            raise AssertionError(f"preview failed: {body.get('error')}")
        await asyncio.sleep(1)
    raise AssertionError(f"preview never became {want}")


async def test_preview_runs_under_runsc_end_to_end(
    client: AsyncClient,  # noqa: F811
    runtime: Settings,
    session_factory,  # noqa: F811
) -> None:
    pid = (await client.post("/projects", json={"name": "Pet Shop"})).json()["id"]
    put = await client.put(f"/projects/{pid}/spec", json=SPEC)
    assert put.status_code == 200, put.text

    r = await client.post(f"/projects/{pid}/previews", json={})
    assert r.status_code == 201, r.text
    created = r.json()
    prev, token = created["id"], created["token"]
    url = f"/projects/{pid}/previews/{prev}"
    await _wait(client, url, "running")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as anon:
        base = f"/previews/{prev}"
        # token required
        assert (await anon.get(f"{base}/pets")).status_code == 401
        assert (await anon.get(f"{base}/pets", headers={TOKEN: "bbp_nope"})).status_code == 401
        # seeded demo data through the host proxy; marked as a preview
        h = {TOKEN: token}
        got = await anon.get(f"{base}/pets", headers=h)
        assert got.status_code == 200, got.text
        assert got.headers["x-preview"] == "true"
        body = got.json()
        total = body.get("total", len(body.get("items", body)))
        assert total == 6
        assert (await anon.get(f"{base}/health", headers=h)).json() == {"status": "ok"}
        made = await anon.post(f"{base}/pets", headers=h, json={"name": "Rex", "age": 3})
        assert made.status_code == 201, made.text
        assert (await anon.get(f"{base}/pets", headers=h)).json()["total"] == 7

        # both containers run under gVisor, on one internal network, with the hardened flags
        row = await _row(session_factory, prev)
        box = DockerSandbox(runtime)
        for sid in (row.db_sandbox, row.app_sandbox):
            info = subprocess.run(
                ["docker", "inspect", f"bbsbx-{sid}", "--format",
                 "{{.HostConfig.Runtime}}|{{.HostConfig.ReadonlyRootfs}}|{{.HostConfig.Privileged}}|{{.Config.User}}"],
                capture_output=True, text=True,
            )  # fmt: skip
            runtime_, ro, priv, user = info.stdout.strip().split("|")
            assert (runtime_, ro, priv) == ("runsc", "true", "false") and user not in ("", "0", "root")
        net = subprocess.run(
            ["docker", "network", "inspect", f"bbsbx-{row.db_sandbox}", "--format", "{{.Internal}}"],
            capture_output=True, text=True,
        )  # fmt: skip
        assert net.stdout.strip() == "true"

        # no egress from the app container (raw IP, DNS, cloud metadata)
        probe = await box.exec(
            row.app_sandbox,
            ["python", "-c", (
                "import socket\n"
                "for h in ('1.1.1.1','169.254.169.254'):\n"
                "    s=socket.socket(); s.settimeout(3)\n"
                "    try: s.connect((h,443)); print('CONNECTED',h)\n"
                "    except OSError: print('BLOCKED',h)\n"
                "try: socket.gethostbyname('example.com'); print('DNS-OK')\n"
                "except OSError: print('DNS-BLOCKED')\n"
            )],
            timeout=30,
        )  # fmt: skip
        assert probe.stdout.split() == ["BLOCKED", "1.1.1.1", "BLOCKED", "169.254.169.254", "DNS-BLOCKED"], probe

        # sleep: idle past the limit -> containers and network gone, code kept
        assert (await ps.sweep(now=datetime.now(UTC) + timedelta(minutes=45))).slept == 1
        assert (await client.get(url)).json()["state"] == "sleeping"
        assert not [c for c in _containers() if row.app_sandbox in c or row.db_sandbox in c]
        assert not [n for n in _networks() if row.db_sandbox in n]
        # wake on request: the same call is answered, data is the seed again (sleep wipes data)
        t0 = time.monotonic()
        woke = await anon.get(f"{base}/pets", headers=h)
        assert woke.status_code == 200, woke.text
        assert woke.json()["total"] == 6
        print(f"wake took {time.monotonic() - t0:.1f}s")
        assert (await client.get(url)).json()["state"] == "running"

        # expiry: stack, network and code are deleted, the token stops working
        code_root = Path(runtime.preview_root or "") / uuid.UUID(prev).hex
        assert code_root.exists()
        async with session_factory() as s:
            await s.execute(
                update(Preview).where(Preview.id == uuid.UUID(prev))
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )  # fmt: skip
            await s.commit()
        assert (await ps.sweep()).expired == 1
        assert (await client.get(url)).json()["state"] == "expired"
        assert not code_root.exists()
        assert not [c for c in _containers() if row.app_sandbox in c or row.db_sandbox in c]
        assert not [n for n in _networks() if row.db_sandbox in n]
        assert (await anon.get(f"{base}/pets", headers=h)).status_code == 401


async def _row(session_factory, prev: str) -> Preview:  # noqa: F811
    async with session_factory() as s:
        row = await s.get(Preview, uuid.UUID(prev))
        assert row is not None
        return row
