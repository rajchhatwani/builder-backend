"""MCP-M4: non-secret config sections + metrics/reports tools, through the real MCP server."""

import json
import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.models.enums import MemberRole
from app.models.platform import AuditLog, ProjectMember
from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor, add_to_project_org
from tests.api.test_mcp_lifecycle import Mcp, _enable, _token
from tests.api.test_metrics import TOTAL, _guard_amount, project_with_orders

W = ["mcp:read", "mcp:write"]
VALUES: dict[str, dict[str, Any]] = {
    "payments": {
        "provider": "stripe",
        "currencies": ["USD"],
        "success_urls": ["https://shop.example.com/paid"],
        "cancel_urls": ["https://shop.example.com/cart"],
        "roles": {"create": ["customer"], "read": ["customer"]},
        "security": {"webhook_tolerance_seconds": 120, "secrets_from_files": False},
    },
    "storage": {
        "backend": "s3",
        "bucket": "team-uploads",
        "region": "eu-west-1",
        "roles": {"upload": ["member"], "read": ["member"]},
    },
    "documents": {"enabled": True, "rate_limit": "10/minute", "templates": []},
    "observability": {"sample_ratio": 0.25, "service_name": "shop-api", "extra_redact_keys": ["password"]},
    "deployment": {
        "cloud": "aws",
        "region": "eu-west-1",
        "github_repo": "acme/notes",
        "environments": [{"name": "dev", "profile": "small"}],
    },
}
TIMES = ("updated_at", "created_at")


def _plain(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if k not in TIMES}


async def _project(client: AsyncClient, sf: Any) -> str:
    pid = await make_project(client)
    await _enable(sf, client, pid)
    return pid


async def _member(sf: Any, pid: str, user_id: Any, role: MemberRole) -> None:
    async with sf() as s:
        s.add(ProjectMember(project_id=uuid.UUID(pid), user_id=user_id, role=role, mcp_enabled=True))
        await s.commit()


async def test_config_section_roundtrip_through_tools(client: AsyncClient, session_factory: Any) -> None:
    pid = await _project(client, session_factory)
    m = Mcp(session_factory, await _token(client, W))
    empty = await m.call("get_config_section", {"project_id": pid, "section": "payments"})
    assert empty["saved"] is False and empty["value"] is None
    for section, value in VALUES.items():
        out = await m.call("set_config_section", {"project_id": pid, "section": section, "value": value})
        assert out["saved"] is True and out["section"] == section
        json.dumps(out)
        got = await m.call("get_config_section", {"project_id": pid, "section": section})
        assert got["saved"] is True
        stored = got["value"]
        for k, v in value.items():
            if isinstance(v, dict):
                assert all(stored[k][kk] == vv for kk, vv in v.items()), (section, k)
            elif isinstance(v, list) and section != "deployment":
                assert stored[k] == v, (section, k)
            elif not isinstance(v, list):
                assert stored[k] == v, (section, k)
        rest = await client.get(f"/projects/{pid}/{section}")
        assert rest.status_code == 200
        assert _plain(rest.json()) == _plain(stored), section
    # saving never switches payments/storage on, and says what to do next
    pay = await m.call("set_config_section", {"project_id": pid, "section": "payments", "value": VALUES["payments"]})
    assert pay["enabled"] is False and "dashboard" in pay["next"]
    assert (await m.call("get_config_section", {"project_id": pid, "section": "storage"}))["value"]["enabled"] is False
    # versioned sections refuse a stale write, exactly like REST
    obs = await m.call("get_config_section", {"project_id": pid, "section": "observability"})
    v = obs["value"]["version"]
    ok = await m.call(
        "set_config_section",
        {"project_id": pid, "section": "observability", "value": {"sample_ratio": 0.5}, "expected_version": v},
    )
    assert ok["value"]["version"] == v + 1
    e = await m.err(
        "set_config_section",
        {"project_id": pid, "section": "observability", "value": {"sample_ratio": 0.6}, "expected_version": v},
    )
    assert e["status"] == 409


async def test_config_refuses_secret_fields_and_values_without_echo(
    client: AsyncClient, session_factory: Any
) -> None:
    pid = await _project(client, session_factory)
    m = Mcp(session_factory, await _token(client, W))
    leaks = ["sk_live_51Habcdef0123456789", "whsec_0123456789abcdef", "AKIAIOSFODNN7EXAMPLE",
             "-----BEGIN RSA PRIVATE KEY-----MIIEow", "xoxb-1234-5678-abcd", "ghp_abcdefghijklmnop1234", "hunter2-top"]  # fmt: skip
    cases: list[tuple[str, dict[str, Any], str]] = [
        ("storage", {"bucket": "b", "access_key": leaks[2]}, "access_key"),
        ("storage", {"bucket": "b", "secret_key": leaks[6]}, "secret_key"),
        ("storage", {"bucket": "b", "Password": leaks[6]}, "Password"),
        ("payments", {"security": {"webhook_secret": leaks[1]}}, "security.webhook_secret"),
        ("payments", {"api_key": leaks[0]}, "api_key"),
        ("payments", {"stripeApiKey": leaks[0]}, "stripeApiKey"),
        ("deployment", {"private_key": leaks[3]}, "private_key"),
        ("deployment", {"environments": [{"name": "dev", "client_secret": leaks[6]}]}, "environments[0].client_secret"),
        ("storage", {"bucket": leaks[2]}, "bucket"),
        ("storage", {"region": leaks[0]}, "region"),
        ("deployment", {"github_repo": leaks[5]}, "github_repo"),
        ("documents", {"templates": [{"id": "a", "title": leaks[4]}]}, "templates[0].title"),
        ("observability", {"service_name": leaks[3]}, "service_name"),
        ("observability", {"extra_redact_keys": [leaks[1]]}, "extra_redact_keys[0]"),
    ]  # fmt: skip
    for section, value, path in cases:
        e = await m.err("set_config_section", {"project_id": pid, "section": section, "value": value})
        assert e["code"] == "secret_not_allowed" and e["status"] == 422, (section, value)
        assert path in e["message"] and "dashboard" in e["message"].lower(), e
        blob = json.dumps(e)
        assert not any(x in blob for x in leaks), blob
    async with session_factory() as s:
        details = json.dumps([str(d) for d in (await s.execute(select(AuditLog.detail))).scalars().all()])
    assert not any(x in details for x in leaks)
    # nothing was saved by a refused call
    assert (await m.call("get_config_section", {"project_id": pid, "section": "storage"}))["saved"] is False
    # legit toggles that merely contain the word "secrets" are not false positives
    ok = await m.call("set_config_section", {"project_id": pid, "section": "payments", "value": VALUES["payments"]})
    assert ok["value"]["security"]["secrets_from_files"] is False


async def test_config_unknown_keys_and_section_rejected(client: AsyncClient, session_factory: Any) -> None:
    pid = await _project(client, session_factory)
    m = Mcp(session_factory, await _token(client, W))
    e = await m.err("set_config_section", {"project_id": pid, "section": "billing", "value": {}})
    assert e["code"] == "unknown_section" and "payments" in e["message"] and "deployment" in e["message"]
    e = await m.err("get_config_section", {"project_id": pid, "section": "billing"})
    assert e["code"] == "unknown_section"
    e = await m.err("set_config_section", {"project_id": pid, "section": "payments", "value": {"enabled": True}})
    assert e["code"] == "unknown_keys" and "provider" in e["message"] and "enabled" in e["message"]
    e = await m.err("set_config_section", {"project_id": pid, "section": "observability", "value": {"sampel": 1}})
    assert e["code"] == "unknown_keys" and "sample_ratio" in e["message"]
    e = await m.err("set_config_section", {"project_id": pid, "section": "storage", "value": {"max_file_mb": 0}})
    assert e["code"] == "invalid_input" and e["status"] == 422
    e = await m.err("set_config_section", {"project_id": pid, "section": "storage", "value": {}, "expected_version": 1})
    assert e["code"] == "invalid_input"
    assert (await m.call("get_config_section", {"project_id": pid, "section": "storage"}))["saved"] is False


async def test_config_role_scope_membership_and_pin(
    client: AsyncClient, client_for: ClientFor, session_factory: Any
) -> None:
    pid = await _project(client, session_factory)
    other = await _project(client, session_factory)
    args = {"project_id": pid, "section": "observability", "value": {"sample_ratio": 0.3}}
    ro = Mcp(session_factory, await _token(client, ["mcp:read"]))
    assert (await ro.err("set_config_section", args))["code"] == "insufficient_scope"
    assert (await ro.err("define_metric", {"project_id": pid, "key": "k", "definition": {}}))["status"] == 403
    assert (await ro.call("get_config_section", {"project_id": pid, "section": "observability"}))["saved"] is True
    # token pinned to another project
    pinned = Mcp(session_factory, await _token(client, W, project_id=other))
    assert (await pinned.err("set_config_section", args))["status"] == 404
    assert (await pinned.err("get_config_section", {"project_id": pid, "section": "storage"}))["status"] == 404
    # viewer member: may read, may not write
    viewer_c = await client_for("v@example.com")
    await add_to_project_org(pid, "v@example.com")
    await _member(session_factory, pid, viewer_c.user.id, MemberRole.viewer)  # type: ignore[attr-defined]
    v = Mcp(session_factory, await _token(viewer_c, W))
    assert (await v.err("set_config_section", args))["code"] == "forbidden"
    assert (await v.call("get_config_section", {"project_id": pid, "section": "observability"}))["saved"] is True
    # a stranger in another org cannot see or touch the project
    stranger = await client_for("s@example.com")
    s_ = Mcp(session_factory, await _token(stranger, W))
    assert (await s_.err("set_config_section", args))["status"] == 404
    assert (await s_.err("get_config_section", {"project_id": pid, "section": "storage"}))["status"] == 404
    # MCP not granted for the caller
    async with session_factory() as s:
        mem = await s.get(ProjectMember, (uuid.UUID(pid), client.user.id))  # type: ignore[attr-defined]
        assert mem is not None
        mem.mcp_enabled = False
        await s.commit()
    full = Mcp(session_factory, await _token(client, W))
    assert (await full.err("set_config_section", args))["code"] == "mcp_not_granted"
    assert (await full.err("define_report", {"project_id": pid, "name": "n", "metric_keys": ["a"], "schedule": "0 6 * * *"}))["code"] == "mcp_not_granted"  # fmt: skip


async def test_metrics_and_reports_through_tools(
    client: AsyncClient, client_for: ClientFor, session_factory: Any
) -> None:
    pid = await project_with_orders(client)
    await _enable(session_factory, client, pid)
    m = Mcp(session_factory, await _token(client, W))
    definition = {k: v for k, v in TOTAL.items() if k != "key"}
    made = await m.call("define_metric", {"project_id": pid, "key": "total_amount", "definition": definition})
    assert made["created"] is True and made["version"] == 1
    again = await m.call(
        "define_metric", {"project_id": pid, "key": "total_amount", "definition": {**definition, "label": "Total 2"}}
    )
    assert again["created"] is False and again["version"] == 2 and again["definition"]["label"] == "Total 2"
    count = {"label": "N", "entity": "Order", "agg": "count"}
    assert (await m.call("define_metric", {"project_id": pid, "key": "n_orders", "definition": count}))["created"]
    listed = await m.call("list_metrics", {"project_id": pid})
    assert [x["key"] for x in listed["items"]] == ["n_orders", "total_amount"]
    assert (await m.err("define_metric", {"project_id": pid, "key": "a", "definition": {**count, "key": "b"}}))["code"] == "invalid_input"  # fmt: skip
    bad = await m.err("define_metric", {"project_id": pid, "key": "bad", "definition": {**definition, "field": "ref"}})
    assert bad["status"] == 422 and bad["code"] == "metric_invalid"
    val = await m.call("get_metric_value", {"project_id": pid, "key": "total_amount"})
    assert val["value"] == "30.6" and val["version"] == 2
    assert (await m.err("get_metric_value", {"project_id": pid, "key": "nope"}))["status"] == 404
    # reports
    rep = await m.call(
        "define_report",
        {"project_id": pid, "name": "Daily", "metric_keys": ["total_amount", "n_orders"], "schedule": "0 6 * * *"},
    )
    assert rep["created"] is True and rep["timezone"] == "UTC" and rep["enabled"] is True
    upd = await m.call(
        "define_report",
        {"project_id": pid, "report_id": rep["id"], "name": "Daily 2", "metric_keys": ["total_amount"],
         "schedule": "0 7 * * *", "timezone": "Europe/Berlin"},
    )  # fmt: skip
    assert upd["created"] is False and upd["id"] == rep["id"] and upd["name"] == "Daily 2"
    reports = await m.call("list_reports", {"project_id": pid})
    assert reports["total"] == 1 and reports["items"][0]["schedule"] == "0 7 * * *"
    for over, code in (({"metric_keys": ["ghost"]}, "report_invalid"), ({"schedule": "* * *"}, "report_invalid")):
        e = await m.err("define_report", {"project_id": pid, "name": "x", "metric_keys": ["n_orders"], "schedule": "0 6 * * *", **over})  # fmt: skip
        assert e["code"] == code and e["status"] == 422
    e = await m.err("define_report", {"project_id": pid, "name": "", "metric_keys": ["n_orders"], "schedule": "0 6 * * *"})
    assert e["code"] == "invalid_input"
    run = await m.call("run_report", {"project_id": pid, "report_id": rep["id"]})
    assert run["status"] == "ok" and run["report_id"] == rep["id"]
    assert run["values"]["total_amount"]["value"] == "30.6"
    rest = await client.get(f"/projects/{pid}/reports/{rep['id']}/runs")
    assert rest.json()["total"] == 1
    # role is passed for redaction: field `amount` readable by the owner role only
    await _guard_amount(client, pid)
    assert (await m.call("get_metric_value", {"project_id": pid, "key": "total_amount"}))["value"] == "30.6"
    ed_c = await client_for("ed@example.com")
    await add_to_project_org(pid, "ed@example.com")
    await _member(session_factory, pid, ed_c.user.id, MemberRole.editor)  # type: ignore[attr-defined]
    ed = Mcp(session_factory, await _token(ed_c, W))
    denied = await ed.err("get_metric_value", {"project_id": pid, "key": "total_amount"})
    assert denied["code"] == "field_access_denied" and denied["status"] == 403
    assert (await ed.call("get_metric_value", {"project_id": pid, "key": "n_orders"}))["value"] == 3
    red = await ed.call("run_report", {"project_id": pid, "report_id": rep["id"]})
    assert red["values"]["total_amount"] == {"error": "field_access_denied"}
    # a viewer reads but cannot define or run
    vi_c = await client_for("vi@example.com")
    await add_to_project_org(pid, "vi@example.com")
    await _member(session_factory, pid, vi_c.user.id, MemberRole.viewer)  # type: ignore[attr-defined]
    vi = Mcp(session_factory, await _token(vi_c, W))
    assert (await vi.call("list_metrics", {"project_id": pid}))["total"] == 2
    assert (await vi.call("list_reports", {"project_id": pid}))["total"] == 1
    for tool, a in (
        ("define_metric", {"project_id": pid, "key": "z", "definition": count}),
        ("define_report", {"project_id": pid, "name": "z", "metric_keys": ["n_orders"], "schedule": "0 6 * * *"}),
        ("run_report", {"project_id": pid, "report_id": rep["id"]}),
    ):
        assert (await vi.err(tool, a))["code"] == "forbidden", tool
    # another project never sees the report
    other = await make_project(client, "Other")
    await _enable(session_factory, client, other)
    assert (await m.err("run_report", {"project_id": other, "report_id": rep["id"]}))["status"] == 404
    async with session_factory() as s:
        acts = json.dumps([str(d) for d in (await s.execute(select(AuditLog.detail))).scalars().all()])
    assert "define_metric" in acts and "run_report" in acts


async def test_m4_tools_documented_and_in_playbook(client: AsyncClient, session_factory: Any) -> None:
    from app.api.mcp import INSTRUCTIONS
    from app.services import mcp_catalog as cat

    reads = ("get_config_section", "list_metrics", "get_metric_value", "list_reports")
    writes = ("set_config_section", "define_metric", "define_report", "run_report")
    steps = cat.get_started()["steps"]
    used = {t for s in steps for t in s["tools"]}
    for t in reads + writes:
        h = cat.TOOL_HELP[t]
        assert h["scope"] == ("mcp:read" if t in reads else "mcp:write") and h["example"] and h["next"], t
        assert t in used, t
        assert t in INSTRUCTIONS, t
        json.loads(h["example"].replace("<uuid from list_reports>", "x").replace("<uuid>", "x"))
    by = {s["section"]: s for s in cat.describe_platform()["sections"]}
    for sec in ("payments", "storage", "documents", "observability", "deployment"):
        assert by[sec]["mcp_editable"] and by[sec]["edit_with"].startswith("set_config_section"), sec
    assert by["metrics_layer"]["edit_with"].startswith("define_metric")
    m = Mcp(session_factory, await _token(client, ["mcp:read"]))
    helped = json.dumps(await m.call("describe_platform", {"topic": "tools"}))
    assert "set_config_section" in helped and "run_report" in helped
