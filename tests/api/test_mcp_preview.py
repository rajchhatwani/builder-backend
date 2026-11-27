"""MCP-M3: preview tools + the `mcp:preview` scope, through the real MCP server.

The sandbox stack is the fake one from tests/api/test_previews.py (no Docker)."""

import asyncio
import json
import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.models.enums import MemberRole
from app.models.platform import AuditLog
from tests.api._auth_helpers import make_entity, make_project
from tests.api.conftest import ClientFor, add_to_project_org
from tests.api.test_mcp_lifecycle import Mcp, _enable, _token
from tests.api.test_previews import FakeBox, stack  # noqa: F401  (fixture)

PV = ["mcp:read", "mcp:preview"]
TOOLS = ("create_preview", "get_preview", "get_preview_logs", "kill_preview")


async def _project(client: AsyncClient, sf: Any) -> str:
    pid = await make_project(client)
    await make_entity(client, pid)
    await _enable(sf, client, pid)
    return pid


async def _running(m: Mcp, pid: str, prev: str) -> dict[str, Any]:
    for _ in range(80):
        out: dict[str, Any] = await m.call("get_preview", {"project_id": pid, "preview_id": prev})
        if out["state"] == "running":
            return out
        await asyncio.sleep(0.1)
    raise AssertionError(out)


async def test_preview_lifecycle_through_tools(
    client: AsyncClient, session_factory: Any, stack: dict[str, object]  # noqa: F811
) -> None:
    pid = await _project(client, session_factory)
    m = Mcp(session_factory, await _token(client, PV))
    made = await m.call("create_preview", {"project_id": pid})
    assert made["state"] in ("starting", "running") and made["token"].startswith("bbp_")
    assert made["url_path"] == f"/previews/{made['id']}/" and made["token_header"] == "X-Preview-Token"
    json.dumps(made)
    got = await _running(m, pid, made["id"])
    assert "token" not in got and "limits" not in got
    listed = await m.call("get_preview", {"project_id": pid})
    assert [p["id"] for p in listed["previews"]] == [made["id"]]
    assert made["token"] not in json.dumps(listed)
    killed = await m.call("kill_preview", {"project_id": pid, "preview_id": made["id"]})
    assert killed["state"] == "killed"
    again = await m.call("get_preview", {"project_id": pid, "preview_id": made["id"]})
    assert again["state"] == "killed"
    async with session_factory() as s:
        acts = (await s.execute(select(AuditLog.action))).scalars().all()
    assert "preview.create" in acts and "preview.kill" in acts and "mcp.tool_call" in acts
    # a kill of an already dead preview stays a clean answer, not a 500
    assert (await m.call("kill_preview", {"project_id": pid, "preview_id": made["id"]}))["state"] == "killed"


async def test_preview_logs_redacted_bounded_and_flagged_untrusted(
    client: AsyncClient, session_factory: Any, stack: dict[str, object]  # noqa: F811
) -> None:
    pid = await _project(client, session_factory)
    m = Mcp(session_factory, await _token(client, PV))
    made = await m.call("create_preview", {"project_id": pid})
    await _running(m, pid, made["id"])
    box = stack["box"]
    assert isinstance(box, FakeBox)
    box.log_text = (
        "boot ok\nDATABASE_URL=postgresql://app:hunter2pw@db/app\nSECRET_KEY=abc123xyz\n"
        + "x" * 5000 + "\n" + "\n".join(f"line {i}" for i in range(2000))
    )
    out = await m.call("get_preview_logs", {"project_id": pid, "preview_id": made["id"]})
    blob = json.dumps(out)
    assert "hunter2pw" not in blob and "abc123xyz" not in blob
    assert out["lines"] and len(out["lines"]) <= 200 and all(len(x) <= 500 for x in out["lines"])
    assert len(blob) < 40_000 and "UNTRUSTED" in out["note"]
    await m.call("kill_preview", {"project_id": pid, "preview_id": made["id"]})
    dead = await m.call("get_preview_logs", {"project_id": pid, "preview_id": made["id"]})
    assert dead["lines"] == [] and dead["state"] == "killed"


async def test_preview_scope_escalation(
    client: AsyncClient, session_factory: Any, stack: dict[str, object]  # noqa: F811
) -> None:
    pid = await _project(client, session_factory)
    made = await Mcp(session_factory, await _token(client, PV)).call("create_preview", {"project_id": pid})
    args = {"project_id": pid, "preview_id": made["id"]}
    for scopes in (["mcp:read"], ["mcp:read", "mcp:write"], ["mcp:read", "mcp:write", "mcp:generate", "mcp:destructive"]):
        m = Mcp(session_factory, await _token(client, scopes))
        for tool in TOOLS:
            e = await m.err(tool, args)
            assert e["code"] == "insufficient_scope" and e["status"] == 403, (scopes, tool)
    # the other way round: a preview-only token reaches nothing else
    only = Mcp(session_factory, await _token(client, ["mcp:preview"]))
    for tool, a in (
        ("list_projects", {}), ("get_project_status", {"project_id": pid}),
        ("create_entity", {"project_id": pid, "name": "X"}), ("generate_project", {"project_id": pid}),
        ("apply_destructive_op", {"project_id": pid, "op_type": "remove_entity", "payload": {}}),
    ):
        assert (await only.err(tool, a))["code"] == "insufficient_scope", tool
    # the dashboard token endpoint accepts the scope; an unknown scope is still refused
    r = await client.post("/account/tokens", json={"name": "t", "scopes": ["mcp:preview"]})
    assert r.status_code == 201 and "mcp:preview" in r.json()["scopes"]
    bad = await client.post("/account/tokens", json={"name": "t", "scopes": ["mcp:previews"]})
    assert bad.status_code in (400, 422)
    await only.call("kill_preview", args)


async def test_preview_role_membership_pin_and_cross_project(
    client: AsyncClient, client_for: ClientFor, session_factory: Any, stack: dict[str, object]  # noqa: F811
) -> None:
    pid = await _project(client, session_factory)
    other = await _project(client, session_factory)
    m = Mcp(session_factory, await _token(client, PV))
    made = await m.call("create_preview", {"project_id": pid})
    # a preview id of project A is invisible through project B
    e = await m.err("get_preview", {"project_id": other, "preview_id": made["id"]})
    assert e["status"] == 404
    e = await m.err("kill_preview", {"project_id": other, "preview_id": made["id"]})
    assert e["status"] == 404
    assert (await m.err("get_preview_logs", {"project_id": other, "preview_id": made["id"]}))["status"] == 404
    assert (await m.call("get_preview", {"project_id": pid, "preview_id": made["id"]}))["state"] != "killed"
    # token pinned to another project
    pinned = Mcp(session_factory, await _token(client, PV, project_id=other))
    assert (await pinned.err("create_preview", {"project_id": pid}))["status"] == 404
    # a viewer member (MCP on) may not start or stop previews; a stranger sees 404
    viewer_c = await client_for("v@example.com")
    await add_to_project_org(pid, "v@example.com")
    from app.models.platform import ProjectMember

    async with session_factory() as s:
        s.add(ProjectMember(project_id=uuid.UUID(pid), user_id=viewer_c.user.id, role=MemberRole.viewer, mcp_enabled=True))  # type: ignore[attr-defined]
        await s.commit()
    v = Mcp(session_factory, await _token(viewer_c, PV))
    for tool, a in (("create_preview", {"project_id": pid}), ("kill_preview", {"project_id": pid, "preview_id": made["id"]}), ("get_preview", {"project_id": pid})):
        assert (await v.err(tool, a))["code"] == "forbidden", tool
    stranger_c = await client_for("s@example.com")
    s_ = Mcp(session_factory, await _token(stranger_c, PV))
    assert (await s_.err("create_preview", {"project_id": pid}))["status"] == 404
    # MCP not granted for the caller
    async with session_factory() as s:
        mem = await s.get(ProjectMember, (uuid.UUID(pid), client.user.id))  # type: ignore[attr-defined]
        assert mem is not None
        mem.mcp_enabled = False
        await s.commit()
    assert (await m.err("create_preview", {"project_id": pid}))["code"] == "mcp_not_granted"


async def test_preview_limits_ttl_and_kill_switch_are_the_dashboards(
    client: AsyncClient, session_factory: Any, stack: dict[str, object]  # noqa: F811
) -> None:
    from app.models.preview import PreviewPlatformSettings

    pid = await _project(client, session_factory)
    m = Mcp(session_factory, await _token(client, PV))
    first = await m.call("create_preview", {"project_id": pid})
    assert first["expires_at"]
    async with session_factory() as s:
        row = await s.get(PreviewPlatformSettings, 1)
        if row is None:
            row = PreviewPlatformSettings(id=1, limits={})
            s.add(row)
        row.limits = {"max_live_per_user": 1}
        await s.commit()
    e = await m.err("create_preview", {"project_id": pid})
    assert e["status"] in (409, 429) and e["code"]
    # kill switch -> same answer as REST, and the log tool honours it too
    async with session_factory() as s:
        row = await s.get(PreviewPlatformSettings, 1)
        assert row is not None
        row.limits = {}
        row.kill_switch = True
        await s.commit()
    rest = await client.post(f"/projects/{pid}/previews", json={})
    via = await m.err("create_preview", {"project_id": pid})
    assert rest.status_code == 503 and via["status"] == 503 and via["code"] == "previews_disabled"
    assert (await m.err("get_preview_logs", {"project_id": pid, "preview_id": first["id"]}))["status"] == 503


async def test_preview_tools_documented_and_in_playbook(client: AsyncClient, session_factory: Any) -> None:
    from app.services import mcp_catalog as cat

    for t in TOOLS:
        assert cat.TOOL_HELP[t]["scope"] == "mcp:preview" and cat.TOOL_HELP[t]["example"]
    assert "mcp:preview" in cat.SCOPES
    steps = cat.get_started()["steps"]
    assert any("create_preview" in s["tools"] for s in steps)
    assert "not available yet" not in json.dumps(steps)
    m = Mcp(session_factory, await _token(client, ["mcp:read"]))
    assert "mcp:preview" in json.dumps(await m.call("describe_platform", {"topic": "limits"}))
