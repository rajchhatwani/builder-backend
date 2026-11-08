"""GET /projects/{id}/status: the readiness board (issues, counts, sections, one next step)."""

import json
from pathlib import Path
from typing import Any

from httpx import AsyncClient

from tests.api._auth_helpers import make_entity, make_project
from tests.api.conftest import ClientFor, add_to_project_org

FIXTURES = Path(__file__).parent.parent / "fixtures" / "specs"
SECTION_IDS = [
    "model", "auth", "authorization", "payments", "storage", "observability", "deployment",
    "documents", "state_machines", "settings", "history", "hooks", "seed",
]  # fmt: skip


def invoice_spec() -> dict[str, Any]:
    spec: dict[str, Any] = json.loads((FIXTURES / "flow_invoices.json").read_text(encoding="utf-8"))
    return spec


async def status(client: AsyncClient, project_id: str) -> dict[str, Any]:
    r = await client.get(f"/projects/{project_id}/status")
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def section(body: dict[str, Any], section_id: str) -> dict[str, Any]:
    return next(s for s in body["sections"] if s["id"] == section_id)


async def test_an_empty_project_asks_for_the_first_entity(client: AsyncClient) -> None:
    body = await status(client, await make_project(client))
    assert body["ready"] is False and body["issues"] == []
    assert body["next_step"]["id"] == "add_entity" and body["next_step"]["section"] == "model"
    assert body["counts"]["entities"] == 0
    assert [s["id"] for s in body["sections"]] == SECTION_IDS
    assert not any(s["configured"] for s in body["sections"])


async def test_entities_without_sign_in_suggest_auth(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await make_entity(client, project_id, "Item")
    body = await status(client, project_id)
    assert body["ready"] is True and body["issues"] == []
    assert body["next_step"]["id"] == "consider_auth" and body["next_step"]["section"] == "auth"
    assert section(body, "model")["configured"] is True
    assert section(body, "auth")["configured"] is False
    assert body["counts"]["entities"] == 1


async def test_a_valid_project_with_auth_is_ready_to_generate(client: AsyncClient) -> None:
    project_id = await make_project(client)
    assert (await client.put(f"/projects/{project_id}/spec", json=invoice_spec())).status_code == 200
    body = await status(client, project_id)
    assert body["issues"] == [], body["issues"]
    assert body["ready"] is True
    assert body["next_step"]["id"] == "generate" and body["next_step"]["section"] == "generate"
    assert section(body, "auth")["configured"] and section(body, "state_machines")["configured"]
    assert section(body, "authorization")["configured"]
    assert body["counts"]["state_machines"] == 1 and body["counts"]["entities"] == 1


async def test_issues_win_and_point_at_their_area(client: AsyncClient) -> None:
    project_id = await make_project(client)
    assert (await client.put(f"/projects/{project_id}/spec", json=invoice_spec())).status_code == 200
    machines = invoice_spec()["state_machines"]
    machines[0]["transitions"][1]["when"] = "amount +"
    saved = await client.put(
        f"/projects/{project_id}/behavior/state-machines", json={"state_machines": machines}
    )
    assert saved.status_code == 200, saved.text
    body = await status(client, project_id)
    assert body["ready"] is False and len(body["issues"]) == 1
    assert set(body["issues"][0]) == {"path", "code", "message"}
    step = body["next_step"]
    assert step["id"] == "fix_issues" and step["section"] == "state_machines"
    assert step["reason"] == body["issues"][0]["message"]
    assert section(body, "state_machines")["issue_count"] == 1
    assert section(body, "model")["issue_count"] == 0
    # the same issues the validate endpoint (the old Overview source) reports
    report = (await client.post(f"/projects/{project_id}/validate")).json()
    assert body["issues"] == report["issues"]


async def test_status_is_read_only(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/spec", json=invoice_spec())
    before = (await client.get(f"/projects/{project_id}/spec")).json()
    first, second = await status(client, project_id), await status(client, project_id)
    assert first == second
    assert (await client.get(f"/projects/{project_id}/spec")).json() == before
    gens = (await client.get(f"/projects/{project_id}/generations")).json()
    assert gens["total"] == 0


async def test_unknown_project_and_stranger_get_404_viewer_can_read(client_for: ClientFor) -> None:
    owner = await client_for("owner@example.com")
    stranger = await client_for("stranger@example.com")
    viewer = await client_for("viewer@example.com")
    project_id = await make_project(owner)
    await add_to_project_org(project_id, "viewer@example.com")
    added = await owner.post(
        f"/projects/{project_id}/members", json={"email": "viewer@example.com", "role": "viewer"}
    )
    assert added.status_code == 201, added.text
    assert (await viewer.get(f"/projects/{project_id}/status")).status_code == 200
    assert (await stranger.get(f"/projects/{project_id}/status")).status_code == 404
    missing = "00000000-0000-4000-8000-000000000000"
    assert (await owner.get(f"/projects/{missing}/status")).status_code == 404
    assert (await owner.get("/projects/not-a-uuid/status")).status_code in (404, 422)
