"""FB2c B-011: read_gate_report and read_app_logs return real data (real DB, fake sandbox)."""

import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.core.generator import generate
from app.models.agent import AiRun
from app.models.preview import Preview
from app.models.project import Project
from app.services import preview_service, workspace_service
from app.services.agent import tools as agent_tools
from app.services.agent.contract import Actor, Phase, Plan, ToolContext
from app.services.agent.draft import run_spec, spec_seq
from app.services.spec_service import SpecService
from tests.api._auth_helpers import make_entity, make_project

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
_MADE: list[str] = []


@pytest.fixture(autouse=True)
async def _discard(client: AsyncClient) -> Any:
    yield
    while _MADE:
        await client.delete(_MADE.pop())


class Box:
    def __init__(self, text: str) -> None:
        self.text = text
        self.asked: list[str] = []

    async def logs(self, sid: str, tail: int = 2000, since: str | None = None) -> str:
        self.asked.append(sid)
        return self.text


async def _setup(client: AsyncClient, s: AsyncSession, settings: Settings) -> tuple[ToolContext, Path, uuid.UUID]:
    pid = uuid.UUID(await make_project(client))
    await make_entity(client, str(pid))
    r = await client.post(f"/projects/{pid}/workspaces", json={})
    assert r.status_code == 201, r.text
    ws_id = uuid.UUID(r.json()["id"])
    _MADE.append(f"/projects/{pid}/workspaces/{ws_id}")
    wt = Path(settings.workspace_root or "") / str(pid) / "wt" / ws_id.hex
    project = await s.get(Project, pid)
    assert project is not None
    base = await SpecService(s).assemble(pid)
    user = client.user  # type: ignore[attr-defined]
    run = AiRun(
        project_id=pid, created_by=user.id, goal="g", state="running", phase="build", workspace_id=ws_id,
        plan={"base_spec_seq": await spec_seq(s, pid), "base_spec": base.model_dump(mode="json")},
    )  # fmt: skip
    s.add(run)
    await s.commit()
    ctx = ToolContext(
        session=s, settings=get_settings(), org_id=project.organization_id, project_id=pid, run_id=run.id,
        actor=Actor("agent", user.id), phase=Phase.build, plan=Plan(uuid.uuid4(), entities=frozenset({"Item"})),
        workspace_id=ws_id, worktree=str(wt),
    )  # fmt: skip
    return ctx, wt, user.id


@pytest.fixture
def ws_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str) -> Settings:
    s = Settings(environment="test", workspace_root=str(tmp_path / "ws"), workspace_db_admin_url=SecretStr(database_url))
    monkeypatch.setattr(workspace_service, "get_settings", lambda: s)
    return s


async def test_read_gate_report_returns_the_real_latest_report(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], ws_settings: Settings
) -> None:
    async with session_factory() as s:
        ctx, wt, _ = await _setup(client, s, ws_settings)
        spec = await run_spec(s, ctx.run_id, ctx.project_id)
        for rel, content in generate(spec).items():  # a clean draft on disk
            p = wt / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8", newline="\n")
        clean = (await agent_tools.execute(ctx, "read_gate_report", {})).data
        assert clean["available"] is True and clean["report"]["gates"]["G8"] == "pass"
        evil = wt / "app/custom/bad.py"
        evil.parent.mkdir(parents=True, exist_ok=True)
        evil.write_text("import sub" "process\n")
        dirty = (await agent_tools.execute(ctx, "read_gate_report", {})).data
        rep = dirty["report"]
        assert dirty["available"] is True and rep["ok"] is False and rep["gates"]["G8"] == "fail"
        assert any(f["rule_id"] == "g8.banned_import" and f["location"].startswith("app/custom/bad.py") for f in rep["failures"])
        assert rep["report_hash"] != clean["report"]["report_hash"]  # it is the latest, not a stored copy


async def test_read_gate_report_without_a_draft_is_typed_unavailable() -> None:
    from tests.unit.test_agent_tools import make_ctx

    r = await agent_tools.execute(make_ctx(), "read_gate_report", {})
    assert r.ok and r.data == {"report": {}, "available": False}


async def test_read_app_logs_real_redacted_tail_or_typed_no_preview(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], ws_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    box = Box("boot ok\nDATABASE_URL=postgresql://app:hunter2pw@db/app\nAuthorization: Bearer abcdefgh12345678\n")
    monkeypatch.setattr(preview_service, "get_sandbox", lambda s=None: box)
    async with session_factory() as s:
        ctx, _, user_id = await _setup(client, s, ws_settings)
        none = await agent_tools.execute(ctx, "read_app_logs", {})
        assert none.ok and none.data["status"] == "no_preview" and none.data["lines"] == [] and box.asked == []
        now = datetime.now(UTC)
        s.add(Preview(
            project_id=ctx.project_id, workspace_id=ctx.workspace_id, created_by=user_id, state="running",
            token_hash=None, spec_hash="h", db_sandbox="d" * 16, app_sandbox="a" * 16, limits={},
            expires_at=now + timedelta(hours=1),
        ))  # fmt: skip
        await s.commit()
        got = await agent_tools.execute(ctx, "read_app_logs", {})
        assert got.ok and got.data["status"] == "ok" and box.asked == ["a" * 16]
        text = got.data["untrusted_data"]
        assert "boot ok" in text and "hunter2pw" not in text and "abcdefgh12345678" not in text
