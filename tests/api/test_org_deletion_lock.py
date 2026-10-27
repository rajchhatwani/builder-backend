"""Review F-014: an org waiting for deletion takes no new projects or project-pinned tokens."""

from httpx import AsyncClient

from tests.api.conftest import ClientFor


async def _locked_org(client_for: ClientFor) -> tuple[AsyncClient, dict, dict]:
    owner = await client_for("lock-owner@example.com")
    org = (await owner.post("/orgs", json={"name": "Lock", "slug": "lock-co"})).json()
    project = await owner.post(
        "/projects", json={"name": "p", "slug": "p", "organization_id": org["id"]}
    )
    assert project.status_code == 201, project.text
    # a free team org holds one project, so the lock (not the cap) must be what refuses below
    assert (await owner.delete("/orgs/lock-co")).status_code == 202
    return owner, org, project.json()


async def test_locked_org_refuses_new_projects(client_for: ClientFor) -> None:
    owner, org, _ = await _locked_org(client_for)
    r = await owner.post("/projects", json={"name": "q", "slug": "q", "organization_id": org["id"]})
    assert r.status_code == 423 and r.json()["code"] == "org_deletion_pending", r.text
    listing = await owner.get("/orgs/lock-co/projects")
    assert listing.status_code == 423


async def test_locked_org_refuses_tokens_pinned_to_its_projects(client_for: ClientFor) -> None:
    owner, _, project = await _locked_org(client_for)
    r = await owner.post(
        "/account/tokens", json={"name": "x", "scopes": ["read"], "project_id": project["id"]}
    )
    assert r.status_code == 423 and r.json()["code"] == "org_deletion_pending", r.text


async def test_cancelling_the_deletion_unlocks_creation(client_for: ClientFor) -> None:
    owner, org, project = await _locked_org(client_for)
    assert (await owner.post("/orgs/lock-co/deletion/cancel")).status_code == 200
    ok = await owner.post(
        "/account/tokens", json={"name": "x", "scopes": ["read"], "project_id": project["id"]}
    )
    assert ok.status_code == 201, ok.text


async def test_moving_a_project_into_a_locked_org_is_refused(client_for: ClientFor) -> None:
    owner, _, _ = await _locked_org(client_for)
    other = (await owner.post("/orgs", json={"name": "Other", "slug": "other-co"})).json()
    mine = await owner.post(
        "/projects", json={"name": "m", "slug": "m", "organization_id": other["id"]}
    )
    assert mine.status_code == 201, mine.text
    r = await owner.post(
        f"/orgs/other-co/projects/{mine.json()['id']}/transfer",
        json={"to_slug": "lock-co"},
    )
    assert r.status_code in (404, 423), r.text
