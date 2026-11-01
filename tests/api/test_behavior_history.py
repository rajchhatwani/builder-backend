"""Change history in the builder: persistence, issues, spec round trip, generation."""

import json
from pathlib import Path
from typing import Any

from httpx import AsyncClient

from app.core.spec_models import Spec
from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor, add_to_project_org

FIXTURES = Path(__file__).parent.parent / "fixtures" / "specs"


def example() -> dict[str, Any]:
    spec: dict[str, Any] = json.loads((FIXTURES / "history_notes.json").read_text(encoding="utf-8"))
    return spec


async def test_a_new_project_has_no_history_config(client: AsyncClient) -> None:
    project_id = await make_project(client)
    body = (await client.get(f"/projects/{project_id}/behavior/history")).json()
    assert body["version"] == 0 and body["history"] == []
    assert (await client.get(f"/projects/{project_id}/behavior/issues")).json() == {"issues": []}


async def test_put_saves_replaces_and_bumps_the_version(client: AsyncClient) -> None:
    project_id = await make_project(client)
    url = f"/projects/{project_id}/behavior/history"
    saved = await client.put(url, json={"history": example()["history"]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 1 and len(saved.json()["history"]) == 2
    again = await client.put(url, json={"history": []})
    assert again.json()["version"] == 2 and again.json()["history"] == []


async def test_stale_edits_are_refused(client: AsyncClient) -> None:
    project_id = await make_project(client)
    url = f"/projects/{project_id}/behavior/history"
    await client.put(url, json={"history": []})
    assert (await client.put(url, json={"expected_version": 1})).status_code == 200
    stale = await client.put(url, json={"expected_version": 1})
    assert stale.status_code == 409 and stale.json()["code"] == "conflict"


async def test_retention_is_required_and_bodies_are_bounded(client: AsyncClient) -> None:
    project_id = await make_project(client)
    url = f"/projects/{project_id}/behavior/history"
    assert (await client.put(url, json={"history": [{"entity": "Note", "fields": ["a"]}]})).status_code == 422
    too_long = {"entity": "N" * 81, "fields": [], "retention_days": 5}
    assert (await client.put(url, json={"history": [too_long]})).status_code == 422
    many = [{"entity": f"E{i}", "retention_days": 5} for i in range(201)]
    assert (await client.put(url, json={"history": many})).status_code == 422


async def test_drafts_save_and_issues_explain_what_is_wrong(client: AsyncClient) -> None:
    project_id = await make_project(client)
    spec = example()
    await client.put(f"/projects/{project_id}/spec", json={**spec, "history": []})
    history = spec["history"]
    history[0]["retention_days"] = 0
    history[0]["fields"] = ["title", "ghost", "private_note_token"]
    history[1]["view_roles"] = ["ghost"]
    history[1]["entity"] = "Ticket"
    history[1]["fields"] = ["status"]
    base = f"/projects/{project_id}/behavior"
    assert (await client.put(f"{base}/history", json={"history": history})).status_code == 200
    issues = (await client.get(f"{base}/issues")).json()["issues"]
    found = {(i["path"], i["code"]) for i in issues}
    assert ("history[0].retention_days", "invalid_value") in found
    assert ("history[0].fields[1]", "unknown_field") in found
    assert ("history[0].fields[2]", "secret_name") in found
    assert ("history[1].view_roles[0]", "unknown_role") in found
    assert ("history[1].fields[0]", "state_field") in found
    assert (await client.post(f"/projects/{project_id}/validate")).json()["valid"] is False


async def test_the_spec_round_trips_and_generation_includes_the_block(client: AsyncClient) -> None:
    project_id = await make_project(client)
    imported = await client.put(f"/projects/{project_id}/spec", json=example())
    assert imported.status_code == 200, imported.text
    exported = (await client.get(f"/projects/{project_id}/spec")).json()
    assert exported["history"] == Spec.model_validate(example()).model_dump(mode="json")["history"]
    assert (await client.get(f"/projects/{project_id}/behavior/issues")).json() == {"issues": []}
    preview = await client.post(f"/projects/{project_id}/generate/preview")
    assert preview.status_code == 200, preview.text
    paths = {f["path"] for f in preview.json()["files"]}
    assert {"alembic/versions/0007_change_history.py", "app/change_history/purge.py"} <= paths
    await client.put(f"/projects/{project_id}/behavior/history", json={"history": []})
    paths = {f["path"] for f in (await client.post(f"/projects/{project_id}/generate/preview")).json()["files"]}
    assert not any("change_history" in p for p in paths)


async def test_an_import_without_the_section_leaves_it_alone(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/spec", json=example())
    assert (await client.put(f"/projects/{project_id}/spec", json={**example(), "history": []})).status_code == 200
    assert len((await client.get(f"/projects/{project_id}/behavior/history")).json()["history"]) == 2


async def test_unknown_project_is_a_404(client: AsyncClient) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/projects/{missing}/behavior/history")).status_code == 404
    assert (await client.put(f"/projects/{missing}/behavior/history", json={})).status_code == 404


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
    url = f"/projects/{project_id}/behavior/history"
    assert (await viewer.get(url)).status_code == 200
    assert (await viewer.put(url, json={})).status_code == 403
    assert (await stranger.get(url)).status_code == 404
    assert (await stranger.put(url, json={})).status_code == 404
