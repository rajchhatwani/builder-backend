"""Observability settings API: persistence, validation, spec round trip, access rules."""

import json
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from tests.api._auth_helpers import make_project
from tests.api.conftest import ClientFor

FIXTURES = Path(__file__).parent.parent / "fixtures" / "specs"


def blog_spec() -> dict[str, Any]:
    spec: dict[str, Any] = json.loads((FIXTURES / "obs_blog.json").read_text(encoding="utf-8"))
    return spec


async def test_a_new_project_has_nothing_saved_and_nothing_enabled(client: AsyncClient) -> None:
    project_id = await make_project(client)
    body = (await client.get(f"/projects/{project_id}/observability")).json()
    assert body["version"] == 0
    assert body["enabled"] is False
    assert body["recommended_sample_ratio"] == 1.0
    assert body["default_service_name"]
    assert "password" in body["redacted_keys"]


async def test_put_saves_and_bumps_the_version(client: AsyncClient) -> None:
    project_id = await make_project(client)
    url = f"/projects/{project_id}/observability"
    saved = await client.put(
        url, json={"sample_ratio": 0.25, "expected_rps": 100, "extra_redact_keys": ["ssn"]}
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["version"] == 1
    assert body["enabled"] is True
    assert body["sample_ratio"] == 0.25
    assert body["recommended_sample_ratio"] == 0.5  # 200 spans/s budget at 100 rps x 4 spans
    again = await client.put(url, json={**body, "sample_ratio": 0.5})
    assert again.json()["version"] == 2
    assert (await client.get(url)).json()["sample_ratio"] == 0.5


async def test_stale_edits_are_refused(client: AsyncClient) -> None:
    project_id = await make_project(client)
    url = f"/projects/{project_id}/observability"
    await client.put(url, json={})
    ok = await client.put(url, json={"expected_version": 1, "sample_ratio": 0.5})
    assert ok.status_code == 200
    stale = await client.put(url, json={"expected_version": 1, "sample_ratio": 0.2})
    assert stale.status_code == 409
    assert stale.json()["code"] == "conflict"


@pytest.mark.parametrize(
    ("patch", "path"),
    [
        ({"sample_ratio": 1.5}, "observability.sample_ratio"),
        ({"sample_ratio": -0.1}, "observability.sample_ratio"),
        ({"service_name": "Bad Name"}, "observability.service_name"),
        ({"exclude_paths": ["health"]}, "observability.exclude_paths[0]"),
        ({"exclude_paths": ["/a", "/a"]}, "observability.exclude_paths[1]"),
        ({"exclude_paths": ["/x?y=1"]}, "observability.exclude_paths[0]"),
        ({"extra_redact_keys": ["Has Space"]}, "observability.extra_redact_keys[0]"),
        ({"expected_rps": 0}, "observability.expected_rps"),
    ],
)
async def test_drafts_save_but_issues_explain_what_is_wrong(
    client: AsyncClient, patch: dict[str, Any], path: str
) -> None:
    project_id = await make_project(client)
    saved = await client.put(f"/projects/{project_id}/observability", json=patch)
    assert saved.status_code == 200, saved.text
    issues = (await client.get(f"/projects/{project_id}/observability/issues")).json()["issues"]
    assert [i["path"] for i in issues] == [path]
    report = (await client.post(f"/projects/{project_id}/validate")).json()
    assert report["valid"] is False


async def test_a_good_configuration_has_no_issues(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/observability", json={"extra_redact_keys": ["nric"]})
    assert (await client.get(f"/projects/{project_id}/observability/issues")).json() == {
        "issues": []
    }


async def test_the_block_travels_with_the_spec(client: AsyncClient) -> None:
    project_id = await make_project(client, "Obs")
    imported = await client.put(f"/projects/{project_id}/spec", json=blog_spec())
    assert imported.status_code == 200, imported.text
    saved = (await client.get(f"/projects/{project_id}/observability")).json()
    assert saved["sample_ratio"] == 0.25
    assert saved["extra_redact_keys"] == ["ssn", "nric"]
    assert saved["expected_rps"] == 100
    exported = (await client.get(f"/projects/{project_id}/spec")).json()
    assert exported["observability"]["sample_ratio"] == 0.25
    assert exported["observability"]["enabled"] is True


async def test_generation_includes_telemetry_only_when_enabled(client: AsyncClient) -> None:
    project_id = await make_project(client, "Obs")
    await client.put(f"/projects/{project_id}/spec", json=blog_spec())
    preview = await client.post(f"/projects/{project_id}/generate/preview")
    assert preview.status_code == 200, preview.text
    paths = {f["path"] for f in preview.json()["files"]}
    assert {"app/core/telemetry.py", "docs/OBSERVABILITY.md"} <= paths
    assert "deploy/observability/otel-collector.yaml" in paths

    await client.put(f"/projects/{project_id}/observability", json={"enabled": False})
    paths = {
        f["path"]
        for f in (await client.post(f"/projects/{project_id}/generate/preview")).json()["files"]
    }
    assert not any("telemetry" in p or "observability" in p.lower() for p in paths)


async def test_roles_and_isolation(client_for: ClientFor) -> None:
    owner = await client_for("owner@example.com")
    viewer = await client_for("viewer@example.com")
    stranger = await client_for("stranger@example.com")
    project_id = await make_project(owner)
    added = await owner.post(
        f"/projects/{project_id}/members", json={"email": "viewer@example.com", "role": "viewer"}
    )
    assert added.status_code == 201
    base = f"/projects/{project_id}/observability"
    assert (await viewer.get(base)).status_code == 200
    assert (await viewer.get(f"{base}/issues")).status_code == 200
    assert (await viewer.put(base, json={})).status_code == 403
    assert (await stranger.get(base)).status_code == 404
    assert (await stranger.put(base, json={})).status_code == 404
