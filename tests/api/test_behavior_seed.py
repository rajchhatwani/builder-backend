"""Seed profiles in the builder: persistence, issues, spec round trip, generation."""

import json
from pathlib import Path
from typing import Any

from httpx import AsyncClient

from app.core.spec_models import Spec
from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor, add_to_project_org

FIXTURES = Path(__file__).parent.parent / "fixtures" / "specs"


def example() -> dict[str, Any]:
    spec: dict[str, Any] = json.loads((FIXTURES / "seed_demo.json").read_text(encoding="utf-8"))
    return spec


async def test_a_new_project_has_no_seed_profiles(client: AsyncClient) -> None:
    project_id = await make_project(client)
    body = (await client.get(f"/projects/{project_id}/behavior/seed")).json()
    assert body["version"] == 0 and body["seed"] == []
    assert (await client.get(f"/projects/{project_id}/behavior/issues")).json() == {"issues": []}


async def test_put_saves_replaces_and_bumps_the_version(client: AsyncClient) -> None:
    project_id = await make_project(client)
    url = f"/projects/{project_id}/behavior/seed"
    saved = await client.put(url, json={"seed": example()["seed"]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 1 and [p["name"] for p in saved.json()["seed"]] == ["demo", "dev"]
    again = await client.put(url, json={"seed": []})
    assert again.json()["version"] == 2 and again.json()["seed"] == []


async def test_stale_edits_are_refused(client: AsyncClient) -> None:
    project_id = await make_project(client)
    url = f"/projects/{project_id}/behavior/seed"
    await client.put(url, json={"seed": []})
    assert (await client.put(url, json={"expected_version": 1})).status_code == 200
    stale = await client.put(url, json={"expected_version": 1})
    assert stale.status_code == 409 and stale.json()["code"] == "conflict"


async def test_the_body_accepts_nothing_outside_the_schema(client: AsyncClient) -> None:
    project_id = await make_project(client)
    url = f"/projects/{project_id}/behavior/seed"
    profile = example()["seed"][0]
    # an unknown key anywhere (a "code" or "sql" generator option, an extra field on a profile) is refused
    bad_generator = json.loads(json.dumps(profile))
    bad_generator["entities"][0]["fields"][0]["generator"]["sql"] = "DROP TABLE x"
    assert (await client.put(url, json={"seed": [bad_generator]})).status_code == 422
    assert (await client.put(url, json={"seed": [{**profile, "run": "rm -rf /"}]})).status_code == 422
    assert (await client.put(url, json={"seed": [profile], "extra": 1})).status_code == 422
    # sizes are bounded
    many = [{**profile, "name": f"p{i}"} for i in range(21)]
    assert (await client.put(url, json={"seed": many})).status_code == 422
    assert (await client.put(url, json={"seed": [{**profile, "name": "n" * 41}]})).status_code == 422


async def test_drafts_save_and_issues_explain_what_is_wrong(client: AsyncClient) -> None:
    project_id = await make_project(client)
    spec = example()
    await client.put(f"/projects/{project_id}/spec", json={**spec, "seed": []})
    profile = json.loads(json.dumps(spec["seed"][0]))
    profile["tenants"] = 99
    profile["entities"][0]["count"] = 10_001
    profile["entities"][1]["fields"][0]["generator"] = {"type": "int_range", "min": 1, "max": 5}
    profile["entities"][1]["fields"][4]["generator"]["entity"] = "Invoice"
    base = f"/projects/{project_id}/behavior"
    assert (await client.put(f"{base}/seed", json={"seed": [profile]})).status_code == 200
    issues = (await client.get(f"{base}/issues")).json()["issues"]
    found = {(i["path"], i["code"]) for i in issues}
    assert ("seed[0].tenants", "invalid_value") in found
    assert ("seed[0].entities[0].count", "invalid_value") in found
    assert ("seed[0].entities[1].fields[0].generator.type", "type_mismatch") in found
    assert any(code in {"type_mismatch", "self_reference"} and path.endswith("generator.entity") for path, code in found)
    assert (await client.post(f"/projects/{project_id}/validate")).json()["valid"] is False


async def test_the_spec_round_trips_and_generation_includes_the_block(client: AsyncClient) -> None:
    project_id = await make_project(client)
    imported = await client.put(f"/projects/{project_id}/spec", json=example())
    assert imported.status_code == 200, imported.text
    exported = (await client.get(f"/projects/{project_id}/spec")).json()
    assert exported["seed"] == Spec.model_validate(example()).model_dump(mode="json")["seed"]
    assert (await client.get(f"/projects/{project_id}/behavior/issues")).json() == {"issues": []}
    preview = await client.post(f"/projects/{project_id}/generate/preview")
    assert preview.status_code == 200, preview.text
    paths = {f["path"] for f in preview.json()["files"]}
    assert {"alembic/versions/0008_seed.py", "app/seed/engine.py", "app/seed/__main__.py"} <= paths
    await client.put(f"/projects/{project_id}/behavior/seed", json={"seed": []})
    paths = {f["path"] for f in (await client.post(f"/projects/{project_id}/generate/preview")).json()["files"]}
    assert not any(p.startswith("app/seed") for p in paths)


async def test_an_import_without_the_section_leaves_it_alone(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/spec", json=example())
    assert (await client.put(f"/projects/{project_id}/spec", json={**example(), "seed": []})).status_code == 200
    assert len((await client.get(f"/projects/{project_id}/behavior/seed")).json()["seed"]) == 2


async def test_unknown_project_is_a_404(client: AsyncClient) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/projects/{missing}/behavior/seed")).status_code == 404
    assert (await client.put(f"/projects/{missing}/behavior/seed", json={})).status_code == 404


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
    url = f"/projects/{project_id}/behavior/seed"
    assert (await viewer.get(url)).status_code == 200
    assert (await viewer.put(url, json={})).status_code == 403
    assert (await stranger.get(url)).status_code == 404
    assert (await stranger.put(url, json={})).status_code == 404
