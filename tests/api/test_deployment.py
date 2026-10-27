"""Deployment settings API: persistence, validation, plan preview, spec round trip, access rules."""

import json
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from tests.api._auth_helpers import make_project
from tests.api.conftest import add_to_project_org, ClientFor

FIXTURES = Path(__file__).parent.parent / "fixtures" / "specs"


def spec(cloud: str = "aws") -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(
        (FIXTURES / f"deploy_{cloud}.json").read_text(encoding="utf-8")
    )
    return raw


def settings(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "cloud": "aws",
        "region": "eu-west-1",
        "github_repo": "acme/notes",
        "environments": [{"name": "dev", "profile": "small"}],
    }
    body.update(changes)
    return body


async def test_a_new_project_has_nothing_saved_and_deployment_is_off(client: AsyncClient) -> None:
    project_id = await make_project(client)
    body = (await client.get(f"/projects/{project_id}/deployment")).json()
    assert body["version"] == 0
    assert body["enabled"] is False
    assert [e["name"] for e in body["environments"]] == ["dev", "staging", "prod"]


async def test_put_saves_bumps_the_version_and_refuses_stale_edits(client: AsyncClient) -> None:
    project_id = await make_project(client)
    url = f"/projects/{project_id}/deployment"
    saved = await client.put(url, json=settings())
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 1
    assert saved.json()["enabled"] is True
    ok = await client.put(url, json={**settings(region="eu-west-2"), "expected_version": 1})
    assert ok.json()["version"] == 2
    stale = await client.put(url, json={**settings(), "expected_version": 1})
    assert stale.status_code == 409
    assert stale.json()["code"] == "conflict"


@pytest.mark.parametrize(
    ("changes", "path"),
    [
        ({"cloud": "oracle"}, "deployment.cloud"),
        ({"region": "mars"}, "deployment.region"),
        ({"github_repo": ""}, "deployment.github_repo"),
        (
            {"environments": [{"name": "dev", "cpu": 300, "memory": 1024}]},
            "deployment.environments[0].cpu",
        ),
    ],
)
async def test_drafts_save_but_issues_explain_the_problem(
    client: AsyncClient, changes: dict[str, Any], path: str
) -> None:
    project_id = await make_project(client)
    saved = await client.put(f"/projects/{project_id}/deployment", json=settings(**changes))
    assert saved.status_code == 200, saved.text
    issues = (await client.get(f"/projects/{project_id}/deployment/issues")).json()["issues"]
    assert path in [i["path"] for i in issues]
    assert (await client.post(f"/projects/{project_id}/validate")).json()["valid"] is False


async def test_the_plan_turns_settings_into_numbers_and_tfvars_without_saving(
    client: AsyncClient,
) -> None:
    project_id = await make_project(client)
    plan = await client.post(
        f"/projects/{project_id}/deployment/plan",
        json=settings(environments=[{"name": "prod", "profile": "medium", "max_instances": 9}]),
    )
    assert plan.status_code == 200, plan.text
    body = plan.json()
    (prod,) = body["environments"]
    assert (prod["cpu"], prod["memory"], prod["max_instances"]) == (1024, 2048, 9)
    assert prod["deletion_protection"] is True
    assert "max_instances" in prod["tfvars"] and "9" in prod["tfvars"]
    assert [512, 1024] in body["valid_sizes"]
    assert (await client.get(f"/projects/{project_id}/deployment")).json()["version"] == 0


async def test_the_plan_skips_environments_it_cannot_resolve(client: AsyncClient) -> None:
    project_id = await make_project(client)
    body = (
        await client.post(
            f"/projects/{project_id}/deployment/plan",
            json=settings(environments=[{"name": "dev", "profile": "huge"}, {"name": "qa"}]),
        )
    ).json()
    assert [e["name"] for e in body["environments"]] == ["qa"]


async def test_the_block_travels_with_the_spec_and_generation_follows_it(
    client: AsyncClient,
) -> None:
    project_id = await make_project(client, "Notes")
    imported = await client.put(f"/projects/{project_id}/spec", json=spec("gcp"))
    assert imported.status_code == 200, imported.text
    saved = (await client.get(f"/projects/{project_id}/deployment")).json()
    assert saved["cloud"] == "gcp" and saved["region"] == "europe-west1"
    assert [e["name"] for e in saved["environments"]] == ["dev", "staging", "prod"]
    assert (await client.get(f"/projects/{project_id}/spec")).json()["deployment"]["cloud"] == "gcp"
    preview = await client.post(f"/projects/{project_id}/generate/preview")
    paths = {f["path"] for f in preview.json()["files"]}
    assert {".github/workflows/deploy.yml", "deploy/gcp/app.tf", "docs/DEPLOYMENT.md"} <= paths

    await client.put(
        f"/projects/{project_id}/deployment", json=settings(cloud="gcp", enabled=False)
    )
    off = {
        f["path"]
        for f in (await client.post(f"/projects/{project_id}/generate/preview")).json()["files"]
    }
    assert not any(p.startswith(("deploy/", ".github/")) for p in off)


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
    base = f"/projects/{project_id}/deployment"
    assert (await viewer.get(base)).status_code == 200
    assert (await viewer.get(f"{base}/issues")).status_code == 200
    assert (await viewer.put(base, json=settings())).status_code == 403
    # the plan only computes, so a viewer may ask for one
    assert (await viewer.post(f"{base}/plan", json=settings())).status_code == 200
    assert (await stranger.get(base)).status_code == 404
    assert (await stranger.put(base, json=settings())).status_code == 404
    assert (await stranger.post(f"{base}/plan", json=settings())).status_code == 404
