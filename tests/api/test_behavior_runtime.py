"""Settings, sequences and lists in the builder: persistence, issues, spec round trip, generation."""

import json
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.spec_models import Spec
from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor, add_to_project_org

FIXTURES = Path(__file__).parent.parent / "fixtures" / "specs"
SECTIONS = ("settings", "sequences", "lists")


def example() -> dict[str, Any]:
    spec: dict[str, Any] = json.loads((FIXTURES / "runtime_config.json").read_text(encoding="utf-8"))
    return spec


@pytest.mark.parametrize("section", SECTIONS)
async def test_a_new_project_has_nothing_in_the_section(client: AsyncClient, section: str) -> None:
    project_id = await make_project(client)
    body = (await client.get(f"/projects/{project_id}/behavior/{section}")).json()
    assert body["version"] == 0 and body[section] == []
    assert (await client.get(f"/projects/{project_id}/behavior/issues")).json() == {"issues": []}


@pytest.mark.parametrize("section", SECTIONS)
async def test_put_saves_replaces_and_bumps_the_version(client: AsyncClient, section: str) -> None:
    project_id = await make_project(client)
    url = f"/projects/{project_id}/behavior/{section}"
    saved = await client.put(url, json={section: example()[section]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 1
    assert len(saved.json()[section]) == len(example()[section])
    again = await client.put(url, json={section: []})
    assert again.json()["version"] == 2 and again.json()[section] == []


@pytest.mark.parametrize("section", SECTIONS)
async def test_stale_edits_are_refused(client: AsyncClient, section: str) -> None:
    project_id = await make_project(client)
    url = f"/projects/{project_id}/behavior/{section}"
    await client.put(url, json={section: []})
    assert (await client.put(url, json={"expected_version": 1})).status_code == 200
    stale = await client.put(url, json={"expected_version": 1})
    assert stale.status_code == 409 and stale.json()["code"] == "conflict"


async def test_sections_do_not_overwrite_each_other(client: AsyncClient) -> None:
    project_id = await make_project(client)
    base = f"/projects/{project_id}/behavior"
    await client.put(f"{base}/settings", json={"settings": example()["settings"]})
    await client.put(f"{base}/lists", json={"lists": example()["lists"]})
    await client.put(f"{base}/settings", json={"settings": []})
    assert len((await client.get(f"{base}/lists")).json()["lists"]) == 1
    assert (await client.get(f"{base}/sequences")).json()["sequences"] == []


async def test_oversized_bodies_are_refused(client: AsyncClient) -> None:
    project_id = await make_project(client)
    base = f"/projects/{project_id}/behavior"
    too_long = [{"key": "k" * 81, "type": "string", "default": "x"}]
    assert (await client.put(f"{base}/settings", json={"settings": too_long})).status_code == 422
    many = [{"name": f"s{i}"} for i in range(201)]
    assert (await client.put(f"{base}/sequences", json={"sequences": many})).status_code == 422
    assert (await client.put(f"{base}/lists", json={"lists": [{"name": "x", "items": [{"value": "v", "label": "l" * 201}]}]})).status_code == 422
    assert (await client.put(f"{base}/settings", json={"settings": [{"key": "a", "default": 1.5}]})).status_code == 422


async def test_drafts_save_and_issues_explain_what_is_wrong(client: AsyncClient) -> None:
    project_id = await make_project(client)
    spec = example()
    await client.put(f"/projects/{project_id}/spec", json={**spec, "settings": [], "sequences": [], "lists": []})
    base = f"/projects/{project_id}/behavior"
    settings = spec["settings"]
    settings[0]["default"] = "5"  # above its maximum
    settings[1]["edit_roles"] = ["ghost"]
    settings[3]["key"] = "smtp_password"
    assert (await client.put(f"{base}/settings", json={"settings": settings})).status_code == 200
    sequences = spec["sequences"]
    sequences[0]["padding"] = 99
    assert (await client.put(f"{base}/sequences", json={"sequences": sequences})).status_code == 200
    lists = spec["lists"]
    lists[0]["items"][0]["color"] = "red"
    assert (await client.put(f"{base}/lists", json={"lists": lists})).status_code == 200
    issues = (await client.get(f"{base}/issues")).json()["issues"]
    assert {(i["path"], i["code"]) for i in issues} == {
        ("settings[0].default", "out_of_range"),
        ("settings[1].edit_roles[0]", "unknown_role"),
        ("settings[3].key", "secret_name"),
        ("sequences[0].padding", "invalid_value"),
        ("lists[0].items[0].color", "invalid_value"),
    }
    assert (await client.post(f"/projects/{project_id}/validate")).json()["valid"] is False


async def test_the_spec_round_trips_and_generation_includes_the_block(client: AsyncClient) -> None:
    project_id = await make_project(client)
    imported = await client.put(f"/projects/{project_id}/spec", json=example())
    assert imported.status_code == 200, imported.text
    exported = (await client.get(f"/projects/{project_id}/spec")).json()
    expected = Spec.model_validate(example()).model_dump(mode="json")
    for section in SECTIONS:
        assert exported[section] == expected[section]  # same content, defaults filled in
    assert (await client.get(f"/projects/{project_id}/behavior/issues")).json() == {"issues": []}
    saved = (await client.get(f"/projects/{project_id}/behavior/sequences")).json()
    assert [s["name"] for s in saved["sequences"]] == ["invoice_no", "order_no"]
    preview = await client.post(f"/projects/{project_id}/generate/preview")
    assert preview.status_code == 200, preview.text
    paths = {f["path"] for f in preview.json()["files"]}
    assert {"alembic/versions/0006_runtime_config.py", "app/runtime_config/sequences.py"} <= paths
    for section in SECTIONS:
        await client.put(f"/projects/{project_id}/behavior/{section}", json={section: []})
    paths = {f["path"] for f in (await client.post(f"/projects/{project_id}/generate/preview")).json()["files"]}
    assert not any("runtime_config" in p for p in paths)


async def test_an_import_without_the_sections_leaves_them_alone(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/spec", json=example())
    bare = {**example(), "settings": [], "sequences": [], "lists": []}
    assert (await client.put(f"/projects/{project_id}/spec", json=bare)).status_code == 200
    assert len((await client.get(f"/projects/{project_id}/behavior/lists")).json()["lists"]) == 1


async def test_unknown_project_is_a_404(client: AsyncClient) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    for section in SECTIONS:
        assert (await client.get(f"/projects/{missing}/behavior/{section}")).status_code == 404
        assert (await client.put(f"/projects/{missing}/behavior/{section}", json={})).status_code == 404


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
    for section in SECTIONS:
        assert (await viewer.get(f"{base}/{section}")).status_code == 200
        assert (await viewer.put(f"{base}/{section}", json={})).status_code == 403
        assert (await stranger.get(f"{base}/{section}")).status_code == 404
        assert (await stranger.put(f"{base}/{section}", json={})).status_code == 404
