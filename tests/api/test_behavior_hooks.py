"""Custom hooks in the builder: persistence, issues, spec round trip, generation."""

import json
from pathlib import Path
from typing import Any

from httpx import AsyncClient

from app.core.spec_models import Spec
from tests.api._auth_helpers import make_project

FIXTURES = Path(__file__).parent.parent / "fixtures" / "specs"


def example() -> dict[str, Any]:
    spec: dict[str, Any] = json.loads((FIXTURES / "hooks_invoice.json").read_text(encoding="utf-8"))
    return spec


async def test_a_new_project_has_no_hooks(client: AsyncClient) -> None:
    project_id = await make_project(client)
    body = (await client.get(f"/projects/{project_id}/behavior/hooks")).json()
    assert body["version"] == 0 and body["hooks"] == []
    assert (await client.get(f"/projects/{project_id}/behavior/issues")).json() == {"issues": []}


async def test_put_saves_replaces_and_bumps_the_version(client: AsyncClient) -> None:
    project_id = await make_project(client)
    url = f"/projects/{project_id}/behavior/hooks"
    saved = await client.put(url, json={"hooks": example()["hooks"]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 1 and [h["name"] for h in saved.json()["hooks"]] == [
        "match_invoice",
        "notify_approved",
    ]
    again = await client.put(url, json={"hooks": []})
    assert again.json()["version"] == 2 and again.json()["hooks"] == []


async def test_stale_edits_are_refused(client: AsyncClient) -> None:
    project_id = await make_project(client)
    url = f"/projects/{project_id}/behavior/hooks"
    await client.put(url, json={"hooks": []})
    assert (await client.put(url, json={"expected_version": 1})).status_code == 200
    stale = await client.put(url, json={"expected_version": 1})
    assert stale.status_code == 409 and stale.json()["code"] == "conflict"


async def test_bodies_are_bounded_and_shaped(client: AsyncClient) -> None:
    project_id = await make_project(client)
    url = f"/projects/{project_id}/behavior/hooks"
    hook = example()["hooks"][0]
    assert (await client.put(url, json={"hooks": [{"name": "x", "point": "A.save"}]})).status_code == 422
    assert (await client.put(url, json={"hooks": [{**hook, "name": "n" * 81}]})).status_code == 422
    assert (await client.put(url, json={"hooks": [{**hook, "fallback": {"a": [1]}}]})).status_code == 422
    big_fallback = {f"k{i}": 1 for i in range(61)}
    assert (await client.put(url, json={"hooks": [{**hook, "fallback": big_fallback}]})).status_code == 422
    assert (await client.put(url, json={"hooks": [hook] * 201})).status_code == 422
    unknown = {**hook, "surprise": 1}
    saved = await client.put(url, json={"hooks": [unknown]})
    assert saved.status_code == 200 and "surprise" not in saved.json()["hooks"][0]


async def test_drafts_save_and_issues_explain_what_is_wrong(client: AsyncClient) -> None:
    project_id = await make_project(client)
    spec = example()
    await client.put(f"/projects/{project_id}/spec", json={**spec, "hooks": []})
    hooks = spec["hooks"]
    hooks[0]["point"] = "Invoice.transition_guard(ghost)"
    hooks[0]["budget"]["cpu_ms"] = 999999
    hooks[1]["kind"] = "pure"
    hooks[1]["input"]["fields"][0]["name"] = "ghost"
    base = f"/projects/{project_id}/behavior"
    assert (await client.put(f"{base}/hooks", json={"hooks": hooks})).status_code == 200
    issues = (await client.get(f"{base}/issues")).json()["issues"]
    found = {(i["path"], i["code"]) for i in issues}
    assert ("hooks[0].point", "unknown_transition") in found
    assert ("hooks[0].budget.cpu_ms", "over_ceiling") in found
    assert ("hooks[1].input.fields[0].name", "unknown_field") in found
    assert ("hooks[1].budget.rows", "over_ceiling") in found
    assert (await client.post(f"/projects/{project_id}/validate")).json()["valid"] is False
    generated = await client.post(f"/projects/{project_id}/generate/preview")
    assert generated.status_code >= 400


async def test_the_spec_round_trips_and_generation_includes_the_block(client: AsyncClient) -> None:
    project_id = await make_project(client)
    imported = await client.put(f"/projects/{project_id}/spec", json=example())
    assert imported.status_code == 200, imported.text
    exported = (await client.get(f"/projects/{project_id}/spec")).json()
    assert exported["hooks"] == Spec.model_validate(example()).model_dump(mode="json")["hooks"]
    assert (await client.get(f"/projects/{project_id}/behavior/issues")).json() == {"issues": []}
    preview = await client.post(f"/projects/{project_id}/generate/preview")
    assert preview.status_code == 200, preview.text
    paths = {f["path"] for f in preview.json()["files"]}
    assert {
        "app/custom/hooks/match_invoice.py",
        "app/hooks_gen/contracts.py",
        "app/hooks_gen/registry.py",
        "app/platform_gate.py",
        "app/platform_sdk/__init__.py",
        "platform/hooks.json",
        "tests/_gen/test_hook_contracts.py",
    } <= paths
    await client.put(f"/projects/{project_id}/behavior/hooks", json={"hooks": []})
    again = await client.post(f"/projects/{project_id}/generate/preview")
    assert not {f["path"] for f in again.json()["files"]} & {"app/platform_gate.py", "platform/hooks.json"}


async def test_an_unknown_project_is_not_found(client: AsyncClient) -> None:
    ghost = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/projects/{ghost}/behavior/hooks")).status_code == 404
    assert (await client.put(f"/projects/{ghost}/behavior/hooks", json={"hooks": []})).status_code == 404
