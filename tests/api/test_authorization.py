"""Authorization settings API: persistence, spec round trip, validation, simulator, coverage and
the recommender."""

import copy
import json
from pathlib import Path
from typing import Any

from httpx import AsyncClient

from tests.api._auth_helpers import make_auth, make_entity, make_project, make_role
from tests.api.conftest import ClientFor

FIXTURES = Path(__file__).parent.parent / "fixtures" / "specs"


def pbac_spec() -> dict[str, Any]:
    spec: dict[str, Any] = json.loads((FIXTURES / "authz_pbac.json").read_text(encoding="utf-8"))
    return spec


async def project_with_policies(client: AsyncClient) -> str:
    project_id = await make_project(client, "Docs")
    response = await client.put(f"/projects/{project_id}/spec", json=pbac_spec())
    assert response.status_code == 200, response.text
    return project_id


def subject(roles: list[str], user: str = "11111111-1111-1111-1111-111111111111") -> dict[str, Any]:
    return {"id": user, "roles": roles, "email": "a@example.com"}


async def simulate(client: AsyncClient, project_id: str, **body: Any) -> Any:
    return await client.post(f"/projects/{project_id}/authorization/simulate", json=body)


# -- persistence ------------------------------------------------------------------------------


async def test_a_new_project_uses_rbac_and_has_nothing_saved(client: AsyncClient) -> None:
    project_id = await make_project(client)
    body = (await client.get(f"/projects/{project_id}/authorization")).json()
    assert body["model"] == "rbac"
    assert body["policies"] == []
    assert body["version"] == 0


async def test_spec_import_stores_policies_and_the_spec_returns_them(client: AsyncClient) -> None:
    project_id = await project_with_policies(client)
    saved = (await client.get(f"/projects/{project_id}/authorization")).json()
    expected = pbac_spec()["authorization"]
    assert saved["model"] == "pbac"
    assert saved["version"] == 1
    assert [p["id"] for p in saved["policies"]] == [p["id"] for p in expected["policies"]]
    assert saved["attachments"] == expected["attachments"]
    exported = (await client.get(f"/projects/{project_id}/spec")).json()
    assert exported["authorization"]["model"] == "pbac"
    assert exported["authorization"]["attachments"] == expected["attachments"]
    assert exported["authorization"]["policies"][0]["when"] == expected["policies"][0]["when"]
    # re-importing the exported spec is a no-op for the content
    again = await client.put(f"/projects/{project_id}/spec", json=exported)
    assert again.status_code == 200, again.text
    assert (await client.get(f"/projects/{project_id}/authorization")).json()["version"] == 2


async def test_a_spec_without_an_authorization_block_leaves_it_alone(client: AsyncClient) -> None:
    project_id = await project_with_policies(client)
    spec = pbac_spec()
    del spec["authorization"]
    spec["auth"]["permissions"] = []
    assert (await client.put(f"/projects/{project_id}/spec", json=spec)).status_code == 200
    saved = (await client.get(f"/projects/{project_id}/authorization")).json()
    assert saved["model"] == "pbac"
    assert len(saved["policies"]) == 5


async def test_put_replaces_and_bumps_the_version(client: AsyncClient) -> None:
    project_id = await project_with_policies(client)
    body = (await client.get(f"/projects/{project_id}/authorization")).json()
    body["policies"] = body["policies"][:2]
    body["attachments"] = {"*": [p["id"] for p in body["policies"]]}
    response = await client.put(f"/projects/{project_id}/authorization", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    assert len(response.json()["policies"]) == 2


async def test_stale_edits_are_refused_with_409(client: AsyncClient) -> None:
    project_id = await project_with_policies(client)
    body = (await client.get(f"/projects/{project_id}/authorization")).json()
    first = await client.put(
        f"/projects/{project_id}/authorization", json={**body, "expected_version": 1}
    )
    assert first.status_code == 200
    stale = await client.put(
        f"/projects/{project_id}/authorization", json={**body, "expected_version": 1}
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "conflict"


async def test_duplicate_policy_ids_are_refused(client: AsyncClient) -> None:
    project_id = await make_project(client)
    policy = {"id": "p", "effect": "allow", "actions": ["*"], "when": None}
    response = await client.put(
        f"/projects/{project_id}/authorization",
        json={"model": "abac", "policies": [policy, policy]},
    )
    assert response.status_code == 422


async def test_unknown_model_is_refused(client: AsyncClient) -> None:
    project_id = await make_project(client)
    response = await client.put(
        f"/projects/{project_id}/authorization", json={"model": "dac", "policies": []}
    )
    assert response.status_code == 422


# -- validation -------------------------------------------------------------------------------


async def test_saving_work_in_progress_is_allowed_and_issues_explain_it(
    client: AsyncClient,
) -> None:
    project_id = await project_with_policies(client)
    body = (await client.get(f"/projects/{project_id}/authorization")).json()
    body["policies"][0]["when"] = {
        "left": {"resource": "no_such_field"},
        "op": "eq",
        "right": {"literal": "x"},
    }
    saved = await client.put(f"/projects/{project_id}/authorization", json=body)
    assert saved.status_code == 200  # saving never validates against the entities
    issues = (await client.get(f"/projects/{project_id}/authorization/issues")).json()["issues"]
    assert issues
    assert all(i["path"].startswith("authorization") for i in issues)
    report = (await client.post(f"/projects/{project_id}/validate")).json()
    assert report["valid"] is False
    assert any(i["path"].startswith("authorization.policies[0]") for i in report["issues"])


async def test_a_good_spec_has_no_authorization_issues(client: AsyncClient) -> None:
    project_id = await project_with_policies(client)
    issues = (await client.get(f"/projects/{project_id}/authorization/issues")).json()["issues"]
    assert issues == []


async def test_role_permissions_next_to_policies_are_refused_on_import(
    client: AsyncClient,
) -> None:
    project_id = await project_with_policies(client)
    spec = copy.deepcopy(pbac_spec())
    spec["auth"]["permissions"] = [{"entity": "Document", "operation": "list", "roles": ["reader"]}]
    put = await client.put(f"/projects/{project_id}/spec", json=spec)
    assert put.status_code == 422
    assert [d["code"] for d in put.json()["details"]] == ["authz.mixed_models"]


async def test_switching_a_project_that_has_role_permissions_is_reported(
    client: AsyncClient,
) -> None:
    project_id = await make_project(client)
    entity_id = await make_entity(client, project_id, "Doc")
    await make_auth(client, project_id)
    await make_role(client, project_id, "reader")
    permissions = await client.post(
        f"/projects/{project_id}/permissions",
        json={"permissions": [{"entity_id": entity_id, "operation": "list", "roles": ["reader"]}]},
    )
    assert permissions.status_code == 200, permissions.text
    policy = {"id": "all", "effect": "allow", "actions": ["*"], "when": None}
    saved = await client.put(
        f"/projects/{project_id}/authorization", json={"model": "abac", "policies": [policy]}
    )
    assert saved.status_code == 200
    issues = (await client.get(f"/projects/{project_id}/authorization/issues")).json()["issues"]
    assert "authz.mixed_models" in [i["code"] for i in issues]


# -- simulator --------------------------------------------------------------------------------


async def test_simulator_matches_the_policy_semantics(client: AsyncClient) -> None:
    project_id = await project_with_policies(client)

    published = await simulate(
        client,
        project_id,
        entity="Document",
        op="get",
        subject=subject(["reader"]),
        resource={"status": "published"},
    )
    assert published.status_code == 200, published.text
    assert published.json()["allowed"] is True
    assert published.json()["allow_matched"] == ["read_published"]

    draft = await simulate(
        client,
        project_id,
        entity="Document",
        op="get",
        subject=subject(["reader"]),
        resource={"status": "draft"},
    )
    assert draft.json()["allowed"] is False
    assert "default deny" in draft.json()["reason"]

    archived_for_manager = await simulate(
        client,
        project_id,
        entity="Document",
        op="update",
        subject=subject(["manager"]),
        resource={"status": "archived"},
    )
    body = archived_for_manager.json()
    assert body["allowed"] is False  # deny overrides the manager's unconditional allow
    assert body["deny_matched"] == ["archived_is_frozen"]
    assert "manage" in body["allow_matched"]

    editor_own = await simulate(
        client,
        project_id,
        entity="Document",
        op="update",
        subject=subject(["editor"]),
        resource={"status": "draft", "created_by_id": "11111111-1111-1111-1111-111111111111"},
    )
    assert editor_own.json()["allowed"] is True
    editor_other = await simulate(
        client,
        project_id,
        entity="Document",
        op="update",
        subject=subject(["editor"]),
        resource={"status": "draft", "created_by_id": "22222222-2222-2222-2222-222222222222"},
    )
    assert editor_other.json()["allowed"] is False


async def test_simulator_explains_each_policy_and_comparison(client: AsyncClient) -> None:
    project_id = await project_with_policies(client)
    result = (
        await simulate(
            client,
            project_id,
            entity="Document",
            op="update",
            subject=subject(["editor"]),
            resource={"status": "archived", "created_by_id": subject([])["id"]},
        )
    ).json()
    by_policy = {t["policy"]: t for t in result["trace"]}
    assert set(by_policy) == {"archived_is_frozen", "author"}
    assert by_policy["archived_is_frozen"]["condition_met"] is True
    assert by_policy["archived_is_frozen"]["effect"] == "deny"
    assert by_policy["author"]["condition_met"] is True
    leaf = by_policy["archived_is_frozen"]["leaves"][0]
    assert leaf["result"] is True
    assert "status" in leaf["text"]
    assert result["allowed"] is False


async def test_simulator_input_errors(client: AsyncClient) -> None:
    project_id = await project_with_policies(client)
    ok = {"entity": "Document", "op": "get", "subject": subject(["reader"])}
    assert (await simulate(client, project_id, **{**ok, "entity": "Nope"})).status_code == 422
    assert (await simulate(client, project_id, **{**ok, "op": "fly"})).status_code == 422
    bad_roles = {**ok, "subject": {"id": "x", "roles": "reader"}}
    assert (await simulate(client, project_id, **bad_roles)).status_code == 422


async def test_simulator_and_coverage_need_abac_or_pbac(client: AsyncClient) -> None:
    project_id = await make_project(client)
    response = await simulate(
        client, project_id, entity="X", op="get", subject=subject([]), resource={}
    )
    assert response.status_code == 409
    assert (await client.get(f"/projects/{project_id}/authorization/coverage")).status_code == 409


async def test_simulator_refuses_policies_that_do_not_load(client: AsyncClient) -> None:
    project_id = await project_with_policies(client)
    body = (await client.get(f"/projects/{project_id}/authorization")).json()
    body["policies"][0]["when"] = {
        "left": {"resource": "no_such_field"},
        "op": "eq",
        "right": {"literal": "x"},
    }
    await client.put(f"/projects/{project_id}/authorization", json=body)
    response = await simulate(
        client,
        project_id,
        entity="Document",
        op="get",
        subject=subject(["reader"]),
        resource={},
    )
    assert response.status_code == 422
    assert "not valid" in response.json()["message"]


# -- coverage ---------------------------------------------------------------------------------


async def test_coverage_matrix(client: AsyncClient) -> None:
    project_id = await project_with_policies(client)
    body = (await client.get(f"/projects/{project_id}/authorization/coverage")).json()
    assert body["model"] == "pbac"
    rows = {(r["entity"], r["op"]): r for r in body["rows"]}
    delete_doc = rows[("Document", "delete")]
    assert delete_doc["state"] == "open"  # manage has no condition, attached to managers
    assert [a["policy"] for a in delete_doc["allow"]] == ["manage"]
    assert delete_doc["allow"][0]["who"] == "manager"
    assert [d["policy"] for d in delete_doc["deny"]] == ["archived_is_frozen"]
    read = rows[("Document", "list")]
    assert read["state"] == "open"  # the manager's unconditional policy
    comment_get = rows[("Comment", "get")]
    assert comment_get["state"] == "conditional"
    assert comment_get["allow"][0]["who"] == "everyone"
    assert all(r["state"] in {"closed", "conditional", "open"} for r in body["rows"])


async def test_coverage_marks_unreachable_operations_closed(client: AsyncClient) -> None:
    project_id = await project_with_policies(client)
    body = (await client.get(f"/projects/{project_id}/authorization")).json()
    only = [p for p in body["policies"] if p["id"] == "read_published"]
    await client.put(
        f"/projects/{project_id}/authorization",
        json={"model": "abac", "policies": only, "attachments": {}},
    )
    rows = {
        (r["entity"], r["op"]): r["state"]
        for r in (await client.get(f"/projects/{project_id}/authorization/coverage")).json()["rows"]
    }
    assert rows[("Document", "delete")] == "closed"
    assert rows[("Comment", "list")] == "closed"
    assert rows[("Document", "list")] == "conditional"


# -- recommender ------------------------------------------------------------------------------


async def test_recommend_endpoint_explains_itself(client: AsyncClient) -> None:
    pid = await make_project(client)
    simple = (
        await client.post(f"/projects/{pid}/authorization/recommend", json={"roles": 2})
    ).json()
    assert simple["model"] == "rbac"
    assert simple["reasons"]
    hard = (
        await client.post(
            f"/projects/{pid}/authorization/recommend",
            json={"roles": 6, "time_or_network_rules": True, "deny_rules": True},
        )
    ).json()
    assert hard["model"] == "pbac"
    assert any("default deny" in c.lower() for c in hard["cautions"])
    public = (
        await client.post(
            f"/projects/{pid}/authorization/recommend",
            json={"roles": 6, "per_record_rules": True, "public_routes": True},
        )
    ).json()
    assert public["model"] == "rbac"


async def test_recommend_rejects_nonsense(client: AsyncClient) -> None:
    pid = await make_project(client)
    assert (
        await client.post(
            f"/projects/{pid}/authorization/recommend", json={"policy_editors": "robots"}
        )
    ).status_code == 422
    assert (
        await client.post(f"/projects/{pid}/authorization/recommend", json={"roles": -1})
    ).status_code == 422


async def test_recommend_for_a_project_reads_its_spec(client: AsyncClient) -> None:
    project_id = await project_with_policies(client)
    body = (await client.get(f"/projects/{project_id}/authorization/recommendation")).json()
    assert body["model"] in {"abac", "pbac"}  # it has per-record policies and deny rules


# -- who may call what ------------------------------------------------------------------------


async def test_member_roles_and_isolation(client_for: ClientFor) -> None:
    owner = await client_for("owner@example.com")
    viewer = await client_for("viewer@example.com")
    stranger = await client_for("stranger@example.com")
    project_id = await project_with_policies(owner)
    added = await owner.post(
        f"/projects/{project_id}/members", json={"email": "viewer@example.com", "role": "viewer"}
    )
    assert added.status_code == 201

    base = f"/projects/{project_id}/authorization"
    # a viewer reads, simulates (it changes nothing) and cannot save
    assert (await viewer.get(base)).status_code == 200
    assert (await viewer.get(f"{base}/coverage")).status_code == 200
    ok = await simulate(
        viewer, project_id, entity="Document", op="list", subject=subject(["reader"])
    )
    assert ok.status_code == 200
    assert (await viewer.put(base, json={"model": "rbac"})).status_code == 403
    # a stranger learns nothing, not even that the project exists
    for path in (base, f"{base}/coverage", f"{base}/issues", f"{base}/recommendation"):
        assert (await stranger.get(path)).status_code == 404
    assert (await stranger.put(base, json={"model": "rbac"})).status_code == 404
    denied = await simulate(
        stranger, project_id, entity="Document", op="list", subject=subject(["reader"])
    )
    assert denied.status_code == 404
