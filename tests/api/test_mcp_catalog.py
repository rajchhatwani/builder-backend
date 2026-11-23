"""MCP-M1: discoverability (describe_platform, get_started, tool help, error shape, prompt)."""

import json
from types import SimpleNamespace as NS
from typing import Any

import pytest
from httpx import AsyncClient
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.mcp import INSTRUCTIONS, McpLifespan, build_mcp_server
from app.core.spec_models import Spec, SpecPacks
from app.exceptions import AppError
from app.services import mcp_catalog as cat
from app.services.mcp_extra import BLOCKS
from app.services.ops.registry import REGISTRY


def _server(sf: Any) -> Any:
    return build_mcp_server(sf)


def _ctx(sf: Any, token: str | None = None) -> Any:
    headers = {"authorization": f"Bearer {token}"} if token else {}
    return NS(request_context=NS(lifespan_context=McpLifespan(sf)), headers=headers)


async def _token(client: AsyncClient, scopes: list[str]) -> str:
    r = await client.post("/account/tokens", json={"name": "m1", "scopes": scopes})
    assert r.status_code == 201, r.text
    return str(r.json()["token"])


def _payload(res: Any) -> Any:
    sc = getattr(res, "structured_content", None)
    if sc:
        return sc.get("result", sc)
    return json.loads(res.content[0].text)


async def test_every_tool_documented_with_example_and_next(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tools = await _server(session_factory).list_tools()
    names = {t.name for t in tools}
    assert names == set(cat.TOOL_HELP), names ^ set(cat.TOOL_HELP)
    for t in tools:
        d = t.description or ""
        assert "Example args:" in d and "Next tool:" in d and "Scope:" in d, t.name
        assert len(d) > 60, t.name
    for name, h in cat.TOOL_HELP.items():
        assert h["scope"] in cat.SCOPES, name
        assert set(h["next"]) <= names, (name, set(h["next"]) - names)
        json.loads(h["example"].replace("<uuid from list_projects>", "x").replace("<uuid>", "x"))


def test_describe_platform_comes_from_real_registries() -> None:
    d = cat.describe_platform()
    sections = {s["section"] for s in d["sections"]}
    assert sections == set(Spec.model_fields) - {"spec_version"}
    assert {p["pack"] for p in d["packs"]} == set(SpecPacks.model_fields) == {
        "money", "operations", "booking", "ai"
    }  # fmt: skip
    assert all(p["parts"] and p["summary"] for p in d["packs"])
    assert {b["block"] for b in d["blocks"]} == set(BLOCKS)
    assert {o["op_type"] for o in d["op_types"]} == set(REGISTRY)
    ops = {o["op_type"]: o for o in d["op_types"]}
    assert ops["remove_field"]["destructive"] and ops["remove_field"]["tool"] == (
        "apply_destructive_op"
    )
    assert not ops["add_field"]["destructive"]
    by = {s["section"]: s for s in d["sections"]}
    assert by["auth"]["edit_with"] == "set_auth_config"
    assert by["events"]["edit_with"] == "put_behavior_block"
    assert by["payments"]["mcp_editable"] is False  # said honestly, not hidden
    assert "credentials" in " ".join(d["limits"]["cannot_do"]).lower()
    assert set(d["limits"]["scopes"]) == {
        "mcp:read", "mcp:write", "mcp:generate", "mcp:preview", "mcp:destructive"
    }  # fmt: skip
    for s in d["sections"]:  # every named tool exists
        if s["edit_with"]:
            assert s["edit_with"].split(" ")[0] in cat.TOOL_HELP, s


def test_describe_platform_topic_filter_and_unknown_topic() -> None:
    d = cat.describe_platform("packs")
    assert set(d) == {"packs", "topics", "next_tools"}
    with pytest.raises(AppError) as e:
        cat.describe_platform("nope")
    assert e.value.code == "unknown_topic"
    assert cat.error_payload(e.value)["error"]["next_tools"] == ["describe_platform"]


def test_get_started_names_only_real_tools_in_order() -> None:
    g = cat.get_started()
    steps = g["steps"]
    assert [s["step"] for s in steps] == list(range(1, len(steps) + 1))
    used = [t for s in steps for t in s["tools"]]
    assert set(used) <= set(cat.TOOL_HELP)
    first = {s["goal"]: s["step"] for s in steps}
    gen = next(i for i, s in enumerate(steps) if "generate_project" in s["tools"])
    ent = next(i for i, s in enumerate(steps) if "create_entity" in s["tools"])
    val = next(i for i, s in enumerate(steps) if "validate_spec" in s["tools"])
    assert ent < val < gen and first
    assert any("dashboard" in s["notes"] for s in steps)


def test_error_payload_has_hint_and_next_tools_for_every_known_code() -> None:
    for code in cat._ERROR_HINTS:
        e = cat.error_payload(AppError(code, "m", 400))["error"]
        assert e["code"] == code and e["hint"] and isinstance(e["next_tools"], list)
        assert set(e["next_tools"]) <= set(cat.TOOL_HELP)
    g = cat.error_payload(AppError("weird", "boom", 500, [{"k": 1}]))["error"]
    assert g["hint"] and g["next_tools"] and g["details"] == [{"k": 1}]
    assert cat.error_payload(AppError("odd", "x", 422))["error"]["next_tools"][0] == "list_op_types"


def test_server_instructions_cover_the_essentials() -> None:
    words = (
        "get_started", "describe_platform", "mcp:read", "mcp:write", "mcp:generate",
        "mcp:destructive", "dry_run", "SECRETS", "next_tools", "build-a-backend",
    )  # fmt: skip
    for word in words:
        assert word in INSTRUCTIONS, word


async def test_prompt_build_a_backend_registered(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    srv = _server(session_factory)
    assert [p.name for p in await srv.list_prompts()] == ["build-a-backend"]
    got = await srv.get_prompt("build-a-backend", {"what_to_build": "a clinic booking app"})
    text = got.messages[0].content.text
    assert "clinic booking app" in text and "get_started" in text and "dry_run" in text


async def test_tool_errors_use_uniform_shape(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    srv = _server(session_factory)
    with pytest.raises(ToolError) as e:  # no token
        await srv.call_tool("get_started", {}, _ctx(session_factory))
    err = json.loads(str(e.value).split(": ", 1)[1])["error"]
    assert err["code"] == "unauthenticated" and err["hint"] and err["next_tools"]

    ro = await _token(client, ["read"])  # wrong scope (no mcp:read)
    with pytest.raises(ToolError) as e:
        await srv.call_tool("describe_platform", {}, _ctx(session_factory, ro))
    err = json.loads(str(e.value).split(": ", 1)[1])["error"]
    assert err["code"] == "insufficient_scope" and err["status"] == 403 and err["hint"]

    tok = await _token(client, ["mcp:read"])
    with pytest.raises(ToolError) as e:  # malformed project id
        await srv.call_tool("get_data_model", {"project_id": "zzz"}, _ctx(session_factory, tok))
    err = json.loads(str(e.value).split(": ", 1)[1])["error"]
    assert err["code"] == "invalid_project_id" and err["next_tools"] == ["list_projects"]

    with pytest.raises(ToolError) as e:  # bad topic through the tool
        await srv.call_tool("describe_platform", {"topic": "zzz"}, _ctx(session_factory, tok))
    assert json.loads(str(e.value).split(": ", 1)[1])["error"]["code"] == "unknown_topic"


async def test_describe_and_get_started_work_through_the_server(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    srv = _server(session_factory)
    tok = await _token(client, ["mcp:read"])
    ctx = _ctx(session_factory, tok)
    d = _payload(await srv.call_tool("describe_platform", {"topic": "blocks"}, ctx))
    assert {b["block"] for b in d["blocks"]} == set(BLOCKS)
    g = _payload(await srv.call_tool("get_started", {}, ctx))
    assert g["steps"][0]["tools"] == ["describe_platform"]
    text = json.dumps(d) + json.dumps(g)
    assert "bb_pat_" not in text and tok not in text
