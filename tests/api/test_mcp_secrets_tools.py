"""list_secrets_needed and the `missing` / `secrets_needed` extension of get_project_status."""

import json
from typing import Any

from httpx import AsyncClient

from tests.api.test_mcp_lifecycle import NOMAIL, Mcp, _token


async def test_status_has_missing_and_secrets_checklist(
    client: AsyncClient, session_factory: Any
) -> None:
    m = Mcp(session_factory, await _token(client))
    pid = (await m.call("create_project", {"name": "Clinic"}))["id"]
    empty = await m.call("get_project_status", {"project_id": pid})
    assert any(i["area"] == "model" for i in empty["missing"])
    assert empty["secrets_needed"] == []
    await m.call("create_entity", {"project_id": pid, "name": "Patient"})
    await m.call("add_field", {"project_id": pid, "entity_name": "Patient",
                               "field": {"name": "full_name", "type": "string"}})  # fmt: skip
    st = await m.call("get_project_status", {"project_id": pid})
    assert all(i["who"] in ("tool", "human") for i in st["missing"])
    assert "missing_summary" in st
    json.dumps(st)


async def test_list_secrets_needed_names_only(client: AsyncClient, session_factory: Any) -> None:
    m = Mcp(session_factory, await _token(client))
    pid = (await m.call("create_project", {"name": "Shop"}))["id"]
    await m.call("set_auth_config", {"project_id": pid, "config": NOMAIL})
    out = await m.call("list_secrets_needed", {"project_id": pid})
    assert "never" in out["note"].lower() or "Never" in out["note"]
    for item in out["secrets_needed"]:
        assert item["names"] and item["where_to_enter"]
        assert all("=" not in n for n in item["names"])
    again = await m.call("list_secrets_needed", {"project_id": pid})
    assert again["secrets_needed"] == out["secrets_needed"]


async def test_list_secrets_needed_scope_and_membership(
    client: AsyncClient, session_factory: Any
) -> None:
    m = Mcp(session_factory, await _token(client))
    pid = (await m.call("create_project", {"name": "Z"}))["id"]
    bad = await m.err("list_secrets_needed", {"project_id": "not-a-uuid"})
    assert bad["code"] == "invalid_project_id"
    ghost = await m.err(
        "list_secrets_needed", {"project_id": "00000000-0000-0000-0000-000000000001"}
    )
    assert ghost["status"] == 404
    assert pid
