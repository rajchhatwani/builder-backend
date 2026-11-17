"""Foreign ids smuggled in request bodies/queries: the path names the attacker's own project, the
body names the victim's object."""

import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.api._auth_helpers import make_entity, make_project
from tests.api.conftest import ClientFor
from tests.api.test_keycloak import settings as kc_settings
from tests.audit.tenant_rls._world import two_orgs, victim_world


async def test_relation_between_own_and_foreign_entity(client_for: ClientFor) -> None:
    a, b = await two_orgs(client_for)
    pa = await make_project(a, "V")
    ea = await make_entity(a, pa, "Secret")
    pb = await make_project(b, "M")
    eb = await make_entity(b, pb, "Mine")
    for frm, to in ((eb, ea), (ea, eb), (ea, ea)):
        r = await b.post(
            f"/projects/{pb}/relations",
            json={"kind": "one_to_many", "from_entity_id": frm, "to_entity_id": to,
                  "from_name": "x", "to_name": "y"},
        )
        assert r.status_code in (400, 404, 422), r.text
    assert (await a.get(f"/projects/{pa}/relations")).json()["total"] == 0


async def test_permission_matrix_naming_a_foreign_entity(client_for: ClientFor) -> None:
    a, b = await two_orgs(client_for)
    pa = await make_project(a, "V")
    ea = await make_entity(a, pa, "Secret")
    pb = await make_project(b, "M")
    r = await b.post(
        f"/projects/{pb}/permissions",
        json={"permissions": [{"entity_id": ea, "operation": "read", "roles": []}]},
    )
    assert r.status_code in (404, 422), r.text
    assert (await a.get(f"/projects/{pa}/permissions")).json()["total"] == 0


async def test_token_pinned_to_a_foreign_project_is_refused(client_for: ClientFor) -> None:
    a, b = await two_orgs(client_for)
    pa = await make_project(a, "V")
    r = await b.post("/account/tokens", json={"name": "x", "scopes": ["read"], "project_id": pa})
    assert r.status_code in (403, 404, 422), r.text


async def test_workspace_id_of_a_foreign_project_in_run_and_preview_bodies(
    client_for: ClientFor, session_factory: async_sessionmaker  # type: ignore[type-arg]
) -> None:
    a, b = await two_orgs(client_for)
    w = await victim_world(a, session_factory)
    pb = await make_project(b, "M")
    for path, body in (
        (f"/projects/{pb}/agent/runs", {"goal": "steal", "workspace_id": w["ws_id"]}),
        (f"/projects/{pb}/previews", {"workspace_id": w["ws_id"]}),
        (f"/projects/{pb}/requirements/start-run", {"workspace_id": w["ws_id"], "accept_assumptions": True}),
        (f"/projects/{pb}/workspaces/{w['ws_id']}/rollback", {"checkpoint_id": str(uuid.uuid4())}),
    ):
        r = await b.post(path, json=body)
        assert r.status_code in (404, 409, 422, 503) and r.status_code != 201, f"{path}: {r.status_code} {r.text[:100]}"

    # previews are unconfigured here (503 before the ownership check), so ask the service directly
    import pytest

    from app.exceptions import AppError
    from app.services.preview_service import PreviewService

    async with session_factory() as session:
        with pytest.raises(AppError) as exc:
            await PreviewService(session)._workspace_files(uuid.UUID(pb), uuid.UUID(w["ws_id"]))
        assert exc.value.status_code == 404


async def test_migration_plan_against_a_foreign_generation(
    client_for: ClientFor, session_factory: async_sessionmaker  # type: ignore[type-arg]
) -> None:
    a, b = await two_orgs(client_for)
    w = await victim_world(a, session_factory)
    pb = await make_project(b, "M")
    await make_entity(b, pb, "Item")
    r = await b.post(f"/projects/{pb}/migration-plan", json={"against_generation_id": w["generation_id"]})
    assert r.status_code == 404, r.text
    g = await b.get(f"/generations/{w['generation_id']}")
    assert g.status_code == 404


async def test_keycloak_shared_mode_cannot_source_a_foreign_projects_realm(
    client_for: ClientFor,
) -> None:
    """`source_project_id` is a project id in the BODY. Pointing it at another tenant's own-mode
    Keycloak must not copy its realm back to the attacker nor pin the victim's realm/mode."""
    a, b = await two_orgs(client_for)
    pa = await make_project(a, "VictimHub")
    r = await a.put(f"/projects/{pa}/keycloak", json=kc_settings(realm="victim-secret-realm"))
    assert r.status_code == 200, r.text
    pb = await make_project(b, "AttackerPortal")
    r = await b.put(
        f"/projects/{pb}/keycloak",
        json=kc_settings(mode="shared", identity_providers=[], source_project_id=pa),
    )
    assert r.status_code in (404, 422), r.text
    assert "victim-secret-realm" not in r.text
    # the victim can still rename their realm: the attacker is not a "dependent"
    r2 = await a.put(f"/projects/{pa}/keycloak", json=kc_settings(realm="victim-renamed"))
    assert r2.status_code == 200, r2.text
    assert "AttackerPortal" not in r2.text
    dep = await a.get(f"/projects/{pa}/keycloak/impact", params={"action": "disable"})
    assert "AttackerPortal" not in dep.text


async def test_spec_restore_and_at_seq_do_not_cross_projects(client_for: ClientFor) -> None:
    a, b = await two_orgs(client_for)
    pa = await make_project(a, "V")
    await make_entity(a, pa, "SecretEntityName")
    pb = await make_project(b, "M")
    ops = (await a.get(f"/projects/{pa}/spec/ops")).json()
    assert ops  # the victim has history
    seq = 1
    r = await b.get(f"/projects/{pb}/spec/at/{seq}")
    assert "SecretEntityName" not in r.text
    r = await b.get(f"/projects/{pb}/spec/ops")
    assert "SecretEntityName" not in r.text
    r = await b.post(f"/projects/{pb}/spec/restore", json={"seq": seq})
    assert "SecretEntityName" not in r.text
    assert "SecretEntityName" not in (await b.get(f"/projects/{pb}/spec")).text


async def test_search_never_returns_other_tenants_rows(client_for: ClientFor) -> None:
    a, b = await two_orgs(client_for)
    pa = await make_project(a, "V")
    await make_entity(a, pa, "ZebraSecret")
    pb = await make_project(b, "M")
    await make_entity(b, pb, "Zebra")
    await a.post(f"/projects/{pa}/search/reindex")
    await b.post(f"/projects/{pb}/search/reindex")
    r = await b.get(f"/projects/{pb}/search", params={"q": "Zebra"})
    assert "ZebraSecret" not in r.text and pa not in r.text
    r = await b.get(f"/projects/{pb}/search", params={"q": "ZebraSecret", "project_id": pa})
    assert "ZebraSecret" not in r.text and pa not in r.text


async def test_project_patch_cannot_move_it_to_another_org(client_for: ClientFor) -> None:
    a, b = await two_orgs(client_for)
    pb = await make_project(b, "M")
    foreign = (await a.get("/orgs")).json()["items"][0]["id"]
    before = (await b.get(f"/projects/{pb}")).json()
    r = await b.patch(f"/projects/{pb}", json={"organization_id": foreign, "version": before["version"]})
    after = (await b.get(f"/projects/{pb}")).json()
    assert after["organization_id"] == before["organization_id"], r.text
