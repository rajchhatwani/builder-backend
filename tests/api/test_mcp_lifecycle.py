"""MCP lifecycle: create_project, update_role / create_role upsert, role filters, unknown keys, and
write-success trust (every write returns a plain dict through the real server)."""

import json
import uuid
from types import SimpleNamespace as NS
from typing import Any

import pytest
from httpx import AsyncClient
from mcp.server.mcpserver.exceptions import ToolError

from app.api.mcp import McpLifespan, build_mcp_server
from app.core.enums import FieldType
from app.models.enums import MemberRole
from app.models.platform import ProjectMember, Subscription
from tests.api._auth_helpers import make_entity, make_project
from tests.api.conftest import ClientFor

NOMAIL: dict[str, Any] = {"enabled": True, "email_magic_link_enabled": False}
SCOPES = ["mcp:read", "mcp:write"]


def _ctx(sf: Any, token: str) -> Any:
    return NS(
        request_context=NS(lifespan_context=McpLifespan(sf)),
        headers={"authorization": f"Bearer {token}"},
    )


def _payload(res: Any) -> Any:
    sc = getattr(res, "structured_content", None)
    if sc:
        return sc.get("result", sc)
    return json.loads(res.content[0].text)


async def _token(
    client: AsyncClient, scopes: list[str] = SCOPES, project_id: str | None = None
) -> str:
    body: dict[str, Any] = {"name": "lc", "scopes": scopes}
    if project_id:
        body["project_id"] = project_id
    r = await client.post("/account/tokens", json=body)
    assert r.status_code == 201, r.text
    return str(r.json()["token"])


class Mcp:
    def __init__(self, sf: Any, token: str) -> None:
        self.srv = build_mcp_server(sf)
        self.ctx = _ctx(sf, token)

    async def call(self, name: str, args: dict[str, Any]) -> Any:
        return _payload(await self.srv.call_tool(name, args, self.ctx))

    async def err(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        with pytest.raises(ToolError) as e:
            await self.srv.call_tool(name, args, self.ctx)
        return json.loads(str(e.value).split(": ", 1)[1])["error"]  # type: ignore[no-any-return]


async def _enable(sf: Any, client: AsyncClient, pid: str) -> None:
    async with sf() as s:
        m = await s.get(ProjectMember, (uuid.UUID(pid), client.user.id))  # type: ignore[attr-defined]
        assert m is not None
        m.mcp_enabled = True
        await s.commit()


async def _book(client: AsyncClient, pid: str) -> None:
    eid = await make_entity(client, pid, "Book")
    r = await client.post(
        f"/entities/{eid}/fields", json={"name": "title", "type": FieldType.string.value}
    )
    assert r.status_code == 201, r.text


async def test_create_project_happy_path(client: AsyncClient, session_factory: Any) -> None:
    m = Mcp(session_factory, await _token(client))
    out = await m.call("create_project", {"name": "Clinic App", "description": "d"})
    assert out["name"] == "Clinic App" and out["slug"] == "clinic-app"
    assert out["your_role"] == "owner" and out["mcp_enabled"] is True and out["organization_id"]
    json.dumps(out)
    listed = await m.call("list_projects", {})
    assert [p["id"] for p in listed] == [out["id"]] and listed[0]["your_role"] == "owner"
    async with session_factory() as s:
        mem = await s.get(ProjectMember, (uuid.UUID(out["id"]), client.user.id))  # type: ignore[attr-defined]
        assert mem is not None and mem.role == MemberRole.owner and mem.mcp_enabled is True
    status = await m.call("get_project_status", {"project_id": out["id"]})
    assert "next_step" in status
    again = await m.call("create_project", {"name": "Clinic App"})  # derived slug gets -2
    assert again["slug"] == "clinic-app-2"


async def test_create_project_slug_rules(client: AsyncClient, session_factory: Any) -> None:
    m = Mcp(session_factory, await _token(client))
    await m.call("create_project", {"name": "A", "slug": "taken"})
    e = await m.err("create_project", {"name": "B", "slug": "taken"})
    assert e["status"] == 409 and e["code"] == "conflict" and e["hint"]
    bad = await m.err("create_project", {"name": "B", "slug": "Bad Slug!"})
    assert bad["status"] == 422 and bad["details"][0]["path"] == "slug"


async def test_create_project_pinned_token_refused(
    client: AsyncClient, session_factory: Any
) -> None:
    pid = await make_project(client)
    m = Mcp(session_factory, await _token(client, project_id=pid))
    e = await m.err("create_project", {"name": "Nope"})
    assert e["code"] == "pinned_token" and e["status"] == 403 and e["next_tools"] == []


async def test_create_project_needs_write_scope(client: AsyncClient, session_factory: Any) -> None:
    m = Mcp(session_factory, await _token(client, ["mcp:read"]))
    e = await m.err("create_project", {"name": "Nope"})
    assert e["code"] == "insufficient_scope" and e["status"] == 403


async def test_create_project_quota_refused(client: AsyncClient, session_factory: Any) -> None:
    org = next(o for o in (await client.get("/orgs")).json()["items"] if o["kind"] == "personal")
    async with session_factory() as s:
        sub = await s.get(Subscription, uuid.UUID(org["id"]))
        assert sub is not None
        sub.plan_id = "team"  # allows MCP
        sub.project_override = 1
        await s.commit()
    m = Mcp(session_factory, await _token(client))
    await m.call("create_project", {"name": "One"})
    e = await m.err("create_project", {"name": "Two"})
    assert e["code"] == "project_limit" and e["status"] == 402 and e["hint"]
    assert len((await client.get("/projects")).json()["items"]) == 1


async def test_create_project_in_foreign_org_same_error_as_rest(
    client: AsyncClient, client_for: ClientFor, session_factory: Any
) -> None:
    other = await client_for("other@example.com")
    other_org = next(
        o for o in (await other.get("/orgs")).json()["items"] if o["kind"] == "personal"
    )["id"]
    rest = await client.post("/projects", json={"name": "X", "organization_id": other_org})
    m = Mcp(session_factory, await _token(client))
    e = await m.err("create_project", {"name": "X", "organization_id": other_org})
    ghost = await m.err("create_project", {"name": "X", "organization_id": str(uuid.uuid4())})
    assert e["status"] == rest.status_code == 403 and e["code"] == rest.json()["code"]
    assert (ghost["status"], ghost["code"], ghost["message"]) == (
        e["status"], e["code"], e["message"]
    )  # fmt: skip
    bad = await m.err("create_project", {"name": "X", "organization_id": "zzz"})
    assert bad["status"] == 422


async def test_role_writes_return_plain_dicts_and_reread(
    client: AsyncClient, session_factory: Any
) -> None:
    pid = await make_project(client)
    await _enable(session_factory, client, pid)
    await _book(client, pid)
    m = Mcp(session_factory, await _token(client))
    await m.call("set_auth_config", {"project_id": pid, "config": NOMAIL})
    made = await m.call(
        "create_role",
        {"project_id": pid, "role": {"name": "doctor", "label": "Doctor", "invite_only": False}},
    )
    assert made["name"] == "doctor" and made["status"] == "created"
    upd = await m.call(
        "update_role",
        {"project_id": pid, "name": "doctor", "changes": {"invite_only": True, "position": 3}},
    )
    assert upd["status"] == "updated" and upd["invite_only"] is True and upd["position"] == 3
    saved = await m.call(
        "set_permissions",
        {"project_id": pid, "entity_name": "Book", "operation": "list", "roles": ["doctor"]},
    )
    assert saved["status"] == "saved" and saved["roles"] == ["doctor"]
    got = await m.call("list_roles_and_permissions", {"project_id": pid})
    role = next(r for r in got["roles"] if r["name"] == "doctor")
    assert (
        role["invite_only"] is True and role["position"] == 3 and role["self_assignable"] is False
    )
    assert {"entity": "Book", "operation": "list", "roles": ["doctor"], "row_rule": None} in (
        got["permissions"]
    )


async def test_update_role_unknown_role_and_keys(client: AsyncClient, session_factory: Any) -> None:
    pid = await make_project(client)
    await _enable(session_factory, client, pid)
    m = Mcp(session_factory, await _token(client))
    await m.call("create_role", {"project_id": pid, "role": {"name": "doc", "label": "Doc"}})
    e = await m.err("update_role", {"project_id": pid, "name": "ghost", "changes": {"label": "x"}})
    assert e["code"] == "not_found" and e["status"] == 404 and "role 'ghost'" in e["message"]
    e2 = await m.err("update_role", {"project_id": pid, "name": "doc", "changes": {"nope": 1}})
    assert e2["code"] == "unknown_keys" and e2["status"] == 422 and "invite_only" in e2["message"]


async def test_create_role_upsert(client: AsyncClient, session_factory: Any) -> None:
    pid = await make_project(client)
    await _enable(session_factory, client, pid)
    m = Mcp(session_factory, await _token(client))
    await m.call("create_role", {"project_id": pid, "role": {"name": "doc", "label": "Doc"}})
    dup = await m.err(
        "create_role", {"project_id": pid, "role": {"name": "doc", "label": "Doctor"}}
    )
    assert dup["status"] == 409
    out = await m.call(
        "create_role",
        {"project_id": pid, "role": {"name": "doc", "label": "Doctor"}, "upsert": True},
    )
    assert out["status"] == "updated" and out["label"] == "Doctor"
    fresh = await m.call(
        "create_role",
        {"project_id": pid, "role": {"name": "nurse", "label": "Nurse"}, "upsert": True},
    )
    assert fresh["status"] == "created"


async def test_role_weakening_needs_confirm(client: AsyncClient, session_factory: Any) -> None:
    pid = await make_project(client)
    await _enable(session_factory, client, pid)
    await _book(client, pid)
    weak = Mcp(session_factory, await _token(client))
    await weak.call("set_auth_config", {"project_id": pid, "config": NOMAIL})
    await weak.call(
        "create_role",
        {"project_id": pid, "role": {"name": "admin", "label": "Admin", "inherits_from": None}},
    )
    await weak.call("create_role", {"project_id": pid, "role": {"name": "staff", "label": "Staff"}})
    await weak.call(
        "set_permissions",
        {"project_id": pid, "entity_name": "Book", "operation": "list", "roles": ["admin"]},
    )
    # staff inheriting from admin gives staff the access admin has: widening
    args = {"project_id": pid, "name": "staff", "changes": {"inherits_from": "admin"}}
    e = await weak.err("update_role", args)
    assert e["code"] == "access_weakened" and "dashboard" in e["message"]
    e2 = await weak.err("update_role", {**args, "confirm_weakening": True})
    assert e2["code"] == "insufficient_scope"
    strong = Mcp(session_factory, await _token(client, [*SCOPES, "mcp:destructive"]))
    out = await strong.call("update_role", {**args, "confirm_weakening": True})
    assert out["inherits_from"] == "admin"


async def test_set_auth_config_unknown_keys(client: AsyncClient, session_factory: Any) -> None:
    pid = await make_project(client)
    await _enable(session_factory, client, pid)
    m = Mcp(session_factory, await _token(client))
    e = await m.err("set_auth_config", {"project_id": pid, "config": {**NOMAIL, "roles": ["a"]}})
    assert e["code"] == "unknown_keys" and e["status"] == 422
    assert "roles" in e["message"] and "create_role" in e["message"]
    ok = await m.call("set_auth_config", {"project_id": pid, "config": NOMAIL})
    assert ok["enabled"] is True


async def test_list_roles_filters(client: AsyncClient, session_factory: Any) -> None:
    pid = await make_project(client)
    await _enable(session_factory, client, pid)
    await _book(client, pid)
    await make_entity(client, pid, "Note")
    m = Mcp(session_factory, await _token(client))
    await m.call("set_auth_config", {"project_id": pid, "config": NOMAIL})
    for r in ("admin", "viewer"):
        await m.call("create_role", {"project_id": pid, "role": {"name": r, "label": r}})
    for ent, op, roles in (
        ("Book", "list", ["admin"]),
        ("Book", "get", ["admin", "viewer"]),
        ("Note", "list", ["viewer"]),
    ):
        await m.call(
            "set_permissions",
            {"project_id": pid, "entity_name": ent, "operation": op, "roles": roles},
        )
    by_entity = await m.call("list_roles_and_permissions", {"project_id": pid, "entity": "Book"})
    assert {p["entity"] for p in by_entity["permissions"]} == {"Book"}
    assert len(by_entity["permissions"]) == 2 and len(by_entity["roles"]) == 2
    by_role = await m.call("list_roles_and_permissions", {"project_id": pid, "role": "viewer"})
    assert {(p["entity"], p["operation"]) for p in by_role["permissions"]} == {
        ("Book", "get"), ("Note", "list")
    }  # fmt: skip
    both = await m.call(
        "list_roles_and_permissions", {"project_id": pid, "entity": "Book", "role": "admin"}
    )
    assert len(both["permissions"]) == 2
    e = await m.err("list_roles_and_permissions", {"project_id": pid, "entity": "Nope"})
    assert e["code"] == "not_found" and e["status"] == 404
