"""State machines in the builder: persistence, validation issues, spec round trip, generation, access."""

import json
from pathlib import Path
from typing import Any

from httpx import AsyncClient

from app.core.spec_models import Spec
from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor, add_to_project_org

FIXTURES = Path(__file__).parent.parent / "fixtures" / "specs"


def invoice_spec() -> dict[str, Any]:
    spec: dict[str, Any] = json.loads((FIXTURES / "flow_invoices.json").read_text(encoding="utf-8"))
    return spec


async def test_a_new_project_has_no_state_machines(client: AsyncClient) -> None:
    project_id = await make_project(client)
    body = (await client.get(f"/projects/{project_id}/behavior/state-machines")).json()
    assert body["version"] == 0
    assert body["state_machines"] == []
    assert (await client.get(f"/projects/{project_id}/behavior/issues")).json() == {"issues": []}


async def test_put_saves_replaces_and_bumps_the_version(client: AsyncClient) -> None:
    project_id = await make_project(client)
    url = f"/projects/{project_id}/behavior/state-machines"
    machines = invoice_spec()["state_machines"]
    saved = await client.put(url, json={"state_machines": machines})
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 1
    assert saved.json()["state_machines"][0]["transitions"][0]["name"] == "submit"
    again = await client.put(url, json={"state_machines": []})
    assert again.json()["version"] == 2
    assert again.json()["state_machines"] == []


async def test_stale_edits_are_refused(client: AsyncClient) -> None:
    project_id = await make_project(client)
    url = f"/projects/{project_id}/behavior/state-machines"
    await client.put(url, json={"state_machines": []})
    assert (await client.put(url, json={"expected_version": 1})).status_code == 200
    stale = await client.put(url, json={"expected_version": 1})
    assert stale.status_code == 409
    assert stale.json()["code"] == "conflict"


async def test_unknown_keys_are_rejected(client: AsyncClient) -> None:
    project_id = await make_project(client)
    url = f"/projects/{project_id}/behavior/state-machines"
    machines = invoice_spec()["state_machines"]
    machines[0]["transitions"][0]["run"] = "import os"
    # The body model ignores unknown keys; the stored section is the spec model, which does not hold them.
    saved = await client.put(url, json={"state_machines": machines})
    assert saved.status_code == 200
    assert "run" not in json.dumps(saved.json())


async def test_drafts_save_and_issues_explain_what_is_wrong(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/spec", json=invoice_spec())
    machines = invoice_spec()["state_machines"]
    machines[0]["transitions"][1]["when"] = "amount >"
    machines[0]["transitions"][0]["to_state"] = "ghost"
    saved = await client.put(
        f"/projects/{project_id}/behavior/state-machines", json={"state_machines": machines}
    )
    assert saved.status_code == 200
    issues = (await client.get(f"/projects/{project_id}/behavior/issues")).json()["issues"]
    assert {(i["path"], i["code"]) for i in issues} == {
        ("state_machines[0].transitions[0].to_state", "unknown_state"),
        ("state_machines[0].transitions[1].when", "invalid_expression"),
    }
    assert (await client.post(f"/projects/{project_id}/validate")).json()["valid"] is False


async def test_the_block_travels_with_the_spec(client: AsyncClient) -> None:
    project_id = await make_project(client, "Flow")
    imported = await client.put(f"/projects/{project_id}/spec", json=invoice_spec())
    assert imported.status_code == 200, imported.text
    saved = (await client.get(f"/projects/{project_id}/behavior/state-machines")).json()
    assert saved["state_machines"][0]["entity"] == "Invoice"
    exported = (await client.get(f"/projects/{project_id}/spec")).json()
    expected = Spec.model_validate(invoice_spec()).model_dump(mode="json")["state_machines"]
    assert exported["state_machines"] == expected  # same machines, defaults filled in
    assert (await client.get(f"/projects/{project_id}/behavior/issues")).json() == {"issues": []}


async def test_generation_includes_the_engine_only_with_a_state_machine(client: AsyncClient) -> None:
    project_id = await make_project(client, "Flow")
    await client.put(f"/projects/{project_id}/spec", json=invoice_spec())
    preview = await client.post(f"/projects/{project_id}/generate/preview")
    assert preview.status_code == 200, preview.text
    paths = {f["path"] for f in preview.json()["files"]}
    assert {"app/state_machines/engine.py", "app/state_machines/definitions.py"} <= paths

    await client.put(
        f"/projects/{project_id}/behavior/state-machines", json={"state_machines": []}
    )
    paths = {
        f["path"]
        for f in (await client.post(f"/projects/{project_id}/generate/preview")).json()["files"]
    }
    assert not any(p.startswith("app/state_machines") for p in paths)


async def test_roles_and_isolation(client_for: ClientFor) -> None:
    owner = await client_for("owner@example.com")
    viewer = await client_for("viewer@example.com")
    stranger = await client_for("stranger@example.com")
    project_id = await make_project(owner)
    await add_to_project_org(project_id, "viewer@example.com")
    added = await owner.post(
        f"/projects/{project_id}/members", json={"email": "viewer@example.com", "role": "viewer"}
    )
    assert added.status_code == 201
    base = f"/projects/{project_id}/behavior"
    assert (await viewer.get(f"{base}/state-machines")).status_code == 200
    assert (await viewer.get(f"{base}/issues")).status_code == 200
    assert (await viewer.put(f"{base}/state-machines", json={})).status_code == 403
    assert (await stranger.get(f"{base}/state-machines")).status_code == 404
    assert (await stranger.put(f"{base}/state-machines", json={})).status_code == 404
