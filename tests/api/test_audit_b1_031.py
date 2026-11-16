"""Audit B1-031 regressions: SSO verify race, workspace lifecycle/file API, webhook ordering."""

import asyncio
import shutil
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models.agent import AiRun
from app.models.sso import SsoDomain
from app.models.workspace import Workspace
from app.services import dns_txt, workspace_service
from app.services.workspace_service import WorkspaceService
from tests.api._auth_helpers import make_entity, make_project
from tests.api.conftest import ClientFor
from tests.api.test_billing_webhooks import (  # noqa: F401  (fixture)
    _sub,
    _team_org,
    checkout_completed,
    deliver,
    event,
    subscription_obj,
    webhook_configured,
)
from tests.api.test_sso_config import business_org, set_plan  # noqa: F401

Factory = async_sessionmaker[AsyncSession]
CUSTOM = "app/custom/notes.py"


# -- F-0268: verify_domain must not stamp a claim another org took over meanwhile -------------


async def test_verify_does_not_verify_a_claim_taken_over_during_dns(
    client: AsyncClient,
    client_for: ClientFor,
    session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await business_org(client, session_factory)
    added = (await client.post("/orgs/acme/sso/domains", json={"domain": "race.test"})).json()
    entered, release = asyncio.Event(), asyncio.Event()

    async def fake(name: str) -> list[str]:
        entered.set()
        await release.wait()
        return [added["dns_record_value"]]  # A's TXT is correct

    monkeypatch.setattr(dns_txt, "txt_records", fake)
    task = asyncio.create_task(client.post("/orgs/acme/sso/domains/race.test/verify"))
    await asyncio.wait_for(entered.wait(), 10)
    other = await client_for("rival@example.com")
    org_b = (await other.post("/orgs", json={"name": "Rival", "slug": "rival"})).json()["id"]
    await set_plan(session_factory, org_b, "business")
    taken = await other.post("/orgs/rival/sso/domains", json={"domain": "race.test"})
    assert taken.status_code == 201, taken.text
    release.set()
    r = await asyncio.wait_for(task, 10)
    assert r.status_code in (404, 409), r.text
    async with session_factory() as s:
        row = await s.get(SsoDomain, "race.test")
        assert row is not None and str(row.organization_id) == org_b
        assert row.verified_at is None


# -- workspace helpers --------------------------------------------------------------------------

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


@pytest.fixture
def ws_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str) -> Settings:
    s = Settings(
        environment="test",
        workspace_root=str(tmp_path / "ws"),
        workspace_db_admin_url=SecretStr(database_url),
    )
    monkeypatch.setattr(workspace_service, "get_settings", lambda: s)
    return s


_MADE: list[str] = []


@pytest.fixture(autouse=True)
async def _discard_workspaces(client: AsyncClient) -> Any:
    yield
    while _MADE:
        r = await client.delete(_MADE.pop())
        assert r.status_code in (200, 204, 404)


async def _mk(client: AsyncClient, s: Settings) -> tuple[str, str, dict[str, Any], Path]:
    pid = await make_project(client)
    await make_entity(client, pid)
    r = await client.post(f"/projects/{pid}/workspaces", json={})
    assert r.status_code == 201, r.text
    ws = r.json()
    base = f"/projects/{pid}/workspaces/{ws['id']}"
    _MADE.append(base)
    wt = Path(s.workspace_root or "") / pid / "wt" / ws["id"].replace("-", "")
    (wt / "app" / "custom").mkdir(parents=True, exist_ok=True)
    (wt / CUSTOM).write_text("print('v1')\n")
    return pid, base, ws, wt


async def _add_run(factory: Factory, pid: str, ws_id: str, state: str = "running") -> None:
    async with factory() as s:
        s.add(AiRun(project_id=uuid.UUID(pid), workspace_id=uuid.UUID(ws_id), goal="g", state=state))
        await s.commit()


# -- F-0270: a rolled_back workspace is usable ----------------------------------------------------


@needs_git
async def test_rolled_back_workspace_still_serves_files_and_sync(
    client: AsyncClient, ws_settings: Settings, session_factory: Factory
) -> None:
    pid, base, ws, wt = await _mk(client, ws_settings)
    rb = await client.post(f"{base}/rollback", json={"checkpoint_id": ws["checkpoints"][0]["id"]})
    assert rb.status_code == 200 and rb.json()["state"] == "rolled_back", rb.text
    assert (await client.get(f"{base}/files")).status_code == 200
    async with session_factory() as s:
        assert await WorkspaceService(s, ws_settings).sync_generated(
            uuid.UUID(pid), uuid.UUID(ws["id"])
        ) >= 0


# -- F-0269: a file write is workspace activity ------------------------------------------------------


@needs_git
async def test_file_write_touches_updated_at(
    client: AsyncClient, ws_settings: Settings, session_factory: Factory
) -> None:
    import hashlib

    pid, base, ws, wt = await _mk(client, ws_settings)
    old = datetime.now(UTC) - timedelta(days=30)
    async with session_factory() as s:
        await s.execute(
            text("UPDATE workspaces SET updated_at = :t WHERE id = :i"),
            {"t": old, "i": uuid.UUID(ws["id"])},
        )
        await s.commit()
    sha = hashlib.sha256(b"print('v1')\n").hexdigest()
    r = await client.put(
        f"{base}/files/content", json={"path": CUSTOM, "content": "print('v2')\n", "expected_sha256": sha}
    )
    assert r.status_code == 200, r.text
    async with session_factory() as s:
        done = await workspace_service.expire_idle_workspaces(
            s, datetime.now(UTC), timedelta(days=14), ws_settings
        )
    assert done == []
    assert (wt / CUSTOM).read_text() == "print('v2')\n"


# -- F-0274: lifecycle operations refuse while an agent run uses the workspace --------------------------


@needs_git
@pytest.mark.parametrize("op", ["rollback", "checkpoint", "discard"])
async def test_lifecycle_refused_while_a_run_is_active(
    client: AsyncClient, ws_settings: Settings, session_factory: Factory, op: str
) -> None:
    pid, base, ws, wt = await _mk(client, ws_settings)
    await _add_run(session_factory, pid, ws["id"])
    if op == "rollback":
        r = await client.post(f"{base}/rollback", json={"checkpoint_id": ws["checkpoints"][0]["id"]})
    elif op == "checkpoint":
        r = await client.post(f"{base}/checkpoints", json={"label": "x"})
    else:
        r = await client.delete(base)
    assert r.status_code == 409 and r.json()["code"] == "workspace_busy", r.text
    assert wt.exists()
    async with session_factory() as s:  # the run ended: the workspace is usable again
        run = (await s.execute(select(AiRun).where(AiRun.workspace_id == uuid.UUID(ws["id"])))).scalar_one()
        run.state = "applied"
        await s.commit()


# -- F-0273: a failed create that could not drop its databases keeps a row ---------------------------------


@needs_git
async def test_failed_create_keeps_row_when_a_drop_fails(
    client: AsyncClient,
    ws_settings: Settings,
    session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid = await make_project(client)
    await make_entity(client, pid)
    orig_drop = WorkspaceService._drop_dbs

    async def boom(self: Any, *a: Any, **k: Any) -> None:
        raise RuntimeError("checkpoint failed")

    async def failing_drop(self: Any, names: list[str]) -> list[str]:
        await orig_drop(self, names)
        return list(names)  # pretend every drop failed

    with monkeypatch.context() as m:
        m.setattr(WorkspaceService, "_take_checkpoint", boom)
        m.setattr(WorkspaceService, "_drop_dbs", failing_drop)
        with pytest.raises(RuntimeError):
            await client.post(f"/projects/{pid}/workspaces", json={})
    async with session_factory() as s:
        rows = (await s.execute(select(Workspace).where(Workspace.project_id == uuid.UUID(pid)))).scalars().all()
    assert len(rows) == 1 and rows[0].state == "discarded" and rows[0].preview_db_name


# -- F-0275: promote_files failure leaves main clean; promoted_files reads committed content -----------------


@needs_git
async def test_promote_failure_restores_main_and_reads_committed(
    client: AsyncClient, ws_settings: Settings, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid, base, ws, wt = await _mk(client, ws_settings)
    svc = WorkspaceService(session_factory(), ws_settings)
    p = uuid.UUID(pid)
    await svc.promote_files(p, {"app/custom/a.py": b"A1\n"}, "first")
    orig = WorkspaceService._git

    async def flaky(self: Any, cwd: Any, *args: str) -> str:
        if args[0] == "commit":
            raise RuntimeError("index.lock")
        return await orig(self, cwd, *args)

    with monkeypatch.context() as m:
        m.setattr(WorkspaceService, "_git", flaky)
        with pytest.raises(RuntimeError):
            await svc.promote_files(p, {"app/custom/a.py": b"A2\n", "app/custom/b.py": b"B\n"}, "second")
    repo = svc._repo(p)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout
    assert status.strip() == ""
    assert (repo / "app/custom/a.py").read_text() == "A1\n" and not (repo / "app/custom/b.py").exists()
    assert (await svc.promoted_files(p)) == {"app/custom/a.py": "A1\n"}
    # and a retry of the same promotion works (no stale 'no change' verdict)
    assert await svc.promote_files(p, {"app/custom/a.py": b"A2\n"}, "third")


# -- F-0272: checkout and subscription events are not ordered against each other -----------------------------


async def test_subscription_event_older_than_checkout_is_not_dropped(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    webhook_configured: None,  # noqa: F811
) -> None:
    org_id = await _team_org(client)
    t0 = 1_800_000_000
    chk = event("checkout.session.completed", checkout_completed(org_id), created=t0 + 100)
    assert (await deliver(anon_client, chk)).json()["outcome"] == "applied"
    sub = event(
        "customer.subscription.updated", subscription_obj(org_id, period_end=1_900_000_123), created=t0
    )
    assert (await deliver(anon_client, sub)).json()["outcome"] == "applied"
    assert (await _sub(session_factory, org_id)).current_period_end is not None
