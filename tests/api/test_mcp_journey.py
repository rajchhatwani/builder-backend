"""MCP-M5: a scripted fake MCP client builds a clinic-booking backend from an EMPTY org using only
tools, plus the scope audit across mcp:read/write/generate/preview/destructive.

Fake sandbox (tests/api/test_previews.py) and fake model provider only; no Docker, no network."""

import asyncio
import json
from typing import Any

import pytest
from httpx import AsyncClient

from mcp.server.mcpserver.exceptions import ToolError

from app.api.mcp import build_mcp_server
from app.services.mcp_catalog import TOOL_HELP
from tests.api.test_mcp_lifecycle import Mcp, _token
from tests.api.test_previews import FakeBox, stack  # noqa: F401  (fixture)

ALL = ["mcp:read", "mcp:write", "mcp:generate", "mcp:preview"]
SCOPES = ("mcp:read", "mcp:write", "mcp:generate", "mcp:preview", "mcp:destructive")
SECRET_SHAPES = ("sk_live_", "whsec_", "AKIA", "-----BEGIN", "hunter2")

CLINIC = "Clinic"
ENTITIES: dict[str, list[dict[str, Any]]] = {
    "Patient": [
        {"name": "full_name", "type": "string", "required": True},
        {"name": "email", "type": "string", "unique": True},
        {"name": "birth_year", "type": "integer"},
    ],
    "Doctor": [
        {"name": "full_name", "type": "string", "required": True},
        {"name": "specialty", "type": "string"},
    ],
    "Appointment": [
        {"name": "reason", "type": "string"},
        {"name": "starts_at", "type": "datetime", "required": True},
        {
            "name": "status",
            "type": "enum",
            "required": True,
            "enum_values": ["requested", "confirmed", "done", "cancelled"],
            "default": "requested",
        },
    ],
}
STATE_MACHINE = {
    "entity": "Appointment",
    "field": "status",
    "initial": "requested",
    "transitions": [
        {
            "name": "confirm",
            "from_states": ["requested"],
            "to_state": "confirmed",
            "roles": ["doctor", "receptionist"],
        },
        {"name": "complete", "from_states": ["confirmed"], "to_state": "done", "roles": ["doctor"]},
        {
            "name": "cancel",
            "from_states": ["requested", "confirmed"],
            "to_state": "cancelled",
            "roles": ["receptionist", "admin"],
        },
    ],
}


def _blob(x: Any) -> str:
    return json.dumps(x, default=str)


async def _running(m: Mcp, pid: str, prev: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for _ in range(80):
        out = await m.call("get_preview", {"project_id": pid, "preview_id": prev})
        if out["state"] == "running":
            return out
        await asyncio.sleep(0.1)
    raise AssertionError(out)


async def test_empty_org_to_built_backend_using_only_tools(
    client: AsyncClient,
    session_factory: Any,
    stack: dict[str, object],  # noqa: F811
) -> None:
    m = Mcp(session_factory, await _token(client, ALL))
    # 0. discovery for a client that knows nothing
    assert (await m.call("list_projects", {})) == []
    started = await m.call("get_started", {})
    assert "create_project" in _blob(started) and "generate_project" in _blob(started)
    platform = await m.call("describe_platform", {})
    assert "packs" in _blob(platform)

    # 1. project
    proj = await m.call("create_project", {"name": "Clinic Booking", "description": "journey"})
    pid = proj["id"]
    assert proj["your_role"] == "owner" and proj["mcp_enabled"] is True
    first = await m.call("get_project_status", {"project_id": pid})
    assert first["missing"], "an empty project must report what is missing"

    # 2. data model (entities + fields + relations)
    ids: dict[str, str] = {}
    for name, fields in ENTITIES.items():
        made_e = await m.call("create_entity", {"project_id": pid, "name": name})
        ids[name] = made_e["id"]
        for f in fields:
            await m.call("add_field", {"project_id": pid, "entity_name": name, "field": f})
    for src, dst, fn, tn in (
        ("Patient", "Appointment", "appointments", "patient"),
        ("Doctor", "Appointment", "appointments", "doctor"),
    ):
        rel = {
            "kind": "one_to_many",
            "from_entity_id": ids[src],
            "to_entity_id": ids[dst],
            "from_name": fn,
            "to_name": tn,
        }
        await m.call("add_relation", {"project_id": pid, "relation": rel})
    model = await m.call("get_data_model", {"project_id": pid})
    assert {e["name"] for e in model["entities"]} >= set(ENTITIES)

    # 3. auth + roles
    auth = await m.call(
        "set_auth_config",
        {
            "project_id": pid,
            "config": {
                "enabled": True,
                "email_magic_link_enabled": False,
                "app_url": "https://clinic.example.com",
                "smtp_config": {
                    "host": "smtp.example.com",
                    "port": 587,
                    "from_email": "no-reply@clinic.example.com",
                    "from_name": "Clinic",
                },
            },
        },
    )
    assert auth["enabled"] is True
    for role in ("admin", "doctor", "receptionist", "patient"):
        await m.call(
            "create_role", {"project_id": pid, "role": {"name": role, "label": role.title()}}
        )

    # 4. authorization (permissions per entity/operation)
    for ent, ops in {
        "Patient": {
            "list": ["admin", "doctor", "receptionist"],
            "create": ["admin", "receptionist"],
            "update": ["admin", "receptionist"],
            "get": ["admin", "doctor", "receptionist"],
        },
        "Doctor": {"list": ["admin", "doctor", "receptionist", "patient"], "create": ["admin"]},
        "Appointment": {
            "list": ["admin", "doctor", "receptionist", "patient"],
            "create": ["admin", "receptionist", "patient"],
            "update": ["admin", "doctor", "receptionist"],
        },
    }.items():
        for op, roles in ops.items():
            await m.call(
                "set_permissions",
                {"project_id": pid, "entity_name": ent, "operation": op, "roles": roles},
            )
    await m.call("set_authorization", {"project_id": pid, "authorization": {"model": "rbac"}})
    perms = await m.call("list_roles_and_permissions", {"project_id": pid})
    assert "doctor" in _blob(perms) and "Appointment" in _blob(perms)

    # 5. behaviour: state machine (op), settings (op), events block
    await m.call(
        "apply_op",
        {
            "project_id": pid,
            "op_type": "set_section",
            "payload": {"section": "state_machines", "items": [STATE_MACHINE]},
        },
    )
    await m.call(
        "apply_op",
        {
            "project_id": pid,
            "op_type": "set_section",
            "payload": {
                "section": "settings",
                "items": [
                    {
                        "key": "slot_minutes",
                        "type": "int",
                        "default": 30,
                        "minimum": 5,
                        "maximum": 240,
                        "read_roles": [],
                        "edit_roles": ["admin"],
                    }
                ],
            },
        },
    )
    await m.call(
        "put_behavior_block", {"project_id": pid, "block": "events", "value": {"enabled": True}}
    )

    # 6. packs (booking) behind the destructive scope: dry run first, real apply
    booking = {
        "booking": {
            "kinds": [
                {
                    "name": "consult",
                    "mode": "slot",
                    "slot_minutes": 30,
                    "schedule": {"mon": [{"start": "09:00", "end": "17:00"}]},
                }
            ],
            "read_roles": ["admin", "receptionist"],
            "book_roles": ["admin", "receptionist", "patient"],
            "manage_roles": ["admin"],
            "own_only": True,
        }
    }
    refused = await m.err("put_packs", {"project_id": pid, "packs": booking, "dry_run": False})
    assert refused["code"] == "insufficient_scope" or refused["status"] == 403
    dm = Mcp(session_factory, await _token(client, [*ALL, "mcp:destructive"]))
    dry = await dm.call("put_packs", {"project_id": pid, "packs": booking})  # dry_run defaults True
    assert dry["dry_run"] is True
    applied = await dm.call("put_packs", {"project_id": pid, "packs": booking, "dry_run": False})
    assert applied["applied"] is True

    # 7. config + metrics/reports
    await m.call(
        "set_config_section",
        {
            "project_id": pid,
            "section": "observability",
            "value": {"sample_ratio": 0.2, "service_name": "clinic-api"},
        },
    )
    await m.call(
        "define_metric",
        {
            "project_id": pid,
            "key": "appointments_total",
            "definition": {"label": "Appointments", "entity": "Appointment", "agg": "count"},
        },
    )
    assert "appointments_total" in _blob(await m.call("list_metrics", {"project_id": pid}))

    # 8. validate + status: nothing missing except secrets a human must enter
    valid = await m.call("validate_spec", {"project_id": pid})
    assert valid.get("issues", valid.get("errors", [])) == [] or valid.get("valid") is True, valid
    status = await m.call("get_project_status", {"project_id": pid})
    assert not [x for x in status["missing"] if x["who"] == "tool"], status["missing"]
    assert status["missing_summary"].startswith("nothing missing")
    secrets = await m.call("list_secrets_needed", {"project_id": pid})
    assert not any(s in _blob(secrets) for s in SECRET_SHAPES)

    # 9. preview (fake sandbox) then generate
    made = await m.call("create_preview", {"project_id": pid})
    await _running(m, pid, made["id"])
    killed = await m.call("kill_preview", {"project_id": pid, "preview_id": made["id"]})
    assert killed["state"] == "killed"
    gen = await m.call("generate_project", {"project_id": pid})
    assert "download" in _blob(gen).lower() or "url" in _blob(gen).lower()
    gens = await m.call("list_generations", {"project_id": pid})
    assert len(gens) >= 1
    # the whole journey never leaked a secret shape into any tool output
    assert not any(
        s in _blob([started, platform, proj, status, secrets, gen]) for s in SECRET_SHAPES
    )


# ── scope audit: every registered tool against every scope ───────────────────────────────
def _needed_scope(tool: str) -> str:
    return str(TOOL_HELP[tool]["scope"])


def _args(schema: dict[str, Any], pid: str) -> dict[str, Any]:
    """Dummy but schema-valid arguments (required properties only): the scope check must run
    before any lookup, so the values never need to be real."""
    dummy: dict[str, Any] = {
        "string": "x",
        "object": {},
        "array": [],
        "boolean": False,
        "integer": 1,
    }
    out: dict[str, Any] = {}
    for key in schema.get("required", []):
        prop = schema["properties"][key]
        kinds = [prop.get("type")] + [o.get("type") for o in prop.get("anyOf", [])]
        kind = next((k for k in kinds if k and k != "null"), "string")
        out[key] = pid if key.endswith("_id") else dummy.get(kind, "x")
    return out


@pytest.mark.parametrize("scope", SCOPES)
async def test_scope_audit_each_scope_reaches_only_its_tools(
    client: AsyncClient, session_factory: Any, scope: str
) -> None:
    pid = (
        await Mcp(session_factory, await _token(client, ["mcp:read", "mcp:write"])).call(
            "create_project", {"name": "Audit"}
        )
    )["id"]
    m = Mcp(session_factory, await _token(client, [scope]))
    listed = {t.name: t for t in await build_mcp_server(session_factory).list_tools()}
    assert set(listed) == set(TOOL_HELP), set(listed) ^ set(TOOL_HELP)
    for tool in sorted(listed):
        need = _needed_scope(tool)
        try:
            await m.srv.call_tool(tool, _args(listed[tool].input_schema, pid), m.ctx)
            code = None
        except ToolError as e:
            msg = str(e)
            code = (
                json.loads(msg[msg.index("{") :])["error"]["code"] if ": {" in msg else "bad_args"
            )
        except Exception:  # noqa: BLE001  (past the scope check: the dummy values hit real validation)
            code = "past_scope_check"
        if need == scope:
            assert code != "insufficient_scope", (tool, scope, code)
        else:
            # a scope implies nothing else, except write+destructive tokens never reach read-only gaps
            assert code == "insufficient_scope", (tool, "needs", need, "token", scope, "got", code)


def test_docs_list_every_tool_and_scope() -> None:
    from pathlib import Path

    text = (Path(__file__).parents[2] / "docs" / "MCP.md").read_text(encoding="utf-8")
    assert [t for t in TOOL_HELP if f"`{t}`" not in text] == []
    assert [s for s in SCOPES if f"`{s}`" not in text] == []
