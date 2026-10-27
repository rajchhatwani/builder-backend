"""Round 2 gaps (agent 4, row 4d): a locked org's 423 names the org, and the project list
flags projects whose org is waiting for deletion instead of leaving the UI to guess."""

from httpx import AsyncClient

from tests.api.conftest import ClientFor


async def _locked_acme(client: AsyncClient) -> tuple[str, str]:
    org = (await client.post("/orgs", json={"name": "Acme Inc", "slug": "acme"})).json()["id"]
    pid = (await client.post("/projects", json={"name": "App", "organization_id": org})).json()[
        "id"
    ]
    assert (await client.delete("/orgs/acme")).status_code == 202
    return org, pid


async def test_423_from_a_project_route_names_the_org(client: AsyncClient) -> None:
    org, pid = await _locked_acme(client)
    r = await client.get(f"/projects/{pid}")
    assert r.status_code == 423
    detail = r.json()["details"][0]
    assert detail["organization_id"] == org
    assert detail["organization_slug"] == "acme"
    assert detail["organization_name"] == "Acme Inc"
    assert detail["deletion_scheduled_for"]


async def test_423_from_an_org_route_names_the_org(client: AsyncClient) -> None:
    org, _pid = await _locked_acme(client)
    r = await client.get("/orgs/acme/members")
    assert r.status_code == 423
    detail = r.json()["details"][0]
    assert detail["organization_slug"] == "acme"
    assert detail["organization_id"] == org
    assert detail["organization_name"] == "Acme Inc"


async def test_project_list_flags_projects_of_locked_orgs(
    client: AsyncClient, client_for: ClientFor
) -> None:
    _org, locked_pid = await _locked_acme(client)
    free_pid = (await client.post("/projects", json={"name": "Mine"})).json()["id"]
    items = {p["id"]: p for p in (await client.get("/projects")).json()["items"]}
    # Still listed, so the owner sees what will be deleted, but flagged.
    assert items[locked_pid]["organization_locked"] is True
    assert items[locked_pid]["organization_deletion_scheduled_for"]
    assert items[free_pid]["organization_locked"] is False
    assert items[free_pid]["organization_deletion_scheduled_for"] is None


async def test_cancelled_deletion_clears_the_flag(client: AsyncClient) -> None:
    _org, pid = await _locked_acme(client)
    assert (await client.post("/orgs/acme/deletion/cancel")).status_code == 200
    items = {p["id"]: p for p in (await client.get("/projects")).json()["items"]}
    assert items[pid]["organization_locked"] is False
