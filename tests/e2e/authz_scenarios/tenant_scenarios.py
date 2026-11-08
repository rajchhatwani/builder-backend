"""Scenario tests for the generated `authz_tenant` project (Team Tasks): PBAC on a multi-tenant
project with soft delete and a many-to-many relation. Copied into the project's tests/ folder by
tests/e2e/test_authz_stack.py and run against a real Postgres.

Roles: member (default), admin. Every signed-in person is scoped to their organisation first.
Policies (see tests/fixtures/specs/authz_tenant.json):
  everyone: see_team (read tasks and labels), finish_before_delete (deny deleting unfinished tasks)
  member:   own_tasks (create / update tasks they created)
  admin:    admin_all (everything)
"""

import pytest
from httpx import ASGITransport, AsyncClient
from tests._auth_support import outbox, sign_in  # noqa: F401

from app.main import app


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def team(http: AsyncClient) -> tuple[dict, dict, dict]:
    """(admin who founded org A, member of A, admin who founded org B)."""
    boss = await sign_in(http, "boss@example.com", roles=["admin"])
    mia = await sign_in(http, "mia@example.com", roles=["member"], join="boss@example.com", n=1)
    other = await sign_in(http, "other-boss@example.com", roles=["admin"], n=2)
    return boss, mia, other


async def make_task(http: AsyncClient, headers: dict, **body) -> str:  # noqa: ANN003
    response = await http.post("/tasks", json={"title": "t", **body}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_the_organisation_boundary_holds_under_policies(http: AsyncClient) -> None:
    boss, mia, other = await team(http)
    task = await make_task(http, boss)

    assert [t["id"] for t in (await http.get("/tasks", headers=mia)).json()["items"]] == [task]
    assert (await http.get("/tasks", headers=other)).json()["items"] == []
    assert (await http.get(f"/tasks/{task}", headers=other)).status_code == 404
    # an admin of another organisation cannot reach it even with an unconditional allow-all
    assert (
        await http.patch(f"/tasks/{task}", json={"title": "x"}, headers=other)
    ).status_code == 404


async def test_a_member_changes_only_their_own_tasks(http: AsyncClient) -> None:
    boss, mia, _ = await team(http)
    hers = await make_task(http, mia, title="hers")
    his = await make_task(http, boss, title="his")

    assert (
        await http.patch(f"/tasks/{hers}", json={"title": "edited"}, headers=mia)
    ).status_code == 200
    # `own_tasks` does not cover this row: the member can read it but not change it
    assert (
        await http.patch(f"/tasks/{his}", json={"title": "hijack"}, headers=mia)
    ).status_code in (403, 404)
    assert (await http.get(f"/tasks/{his}", headers=mia)).status_code == 200
    assert (await http.get(f"/tasks/{his}", headers=boss)).json()["title"] == "his"


async def test_soft_delete_is_gated_by_the_deny_policy(http: AsyncClient) -> None:
    boss, mia, _ = await team(http)
    open_task = await make_task(http, boss, done=False)
    done_task = await make_task(http, boss, done=True)

    # the deny policy beats the admin's allow-all while the task is unfinished
    assert (await http.delete(f"/tasks/{open_task}", headers=boss)).status_code in (403, 404)
    assert (await http.get(f"/tasks/{open_task}", headers=boss)).status_code == 200
    # members have no delete policy at all
    assert (await http.delete(f"/tasks/{done_task}", headers=mia)).status_code == 403
    # a finished task is deleted softly: hidden from every read, row kept for recovery
    assert (await http.delete(f"/tasks/{done_task}", headers=boss)).status_code == 204
    assert (await http.get(f"/tasks/{done_task}", headers=boss)).status_code == 404
    ids = {t["id"] for t in (await http.get("/tasks", headers=boss)).json()["items"]}
    assert done_task not in ids and open_task in ids


async def test_relation_payloads_are_checked_like_any_other_write(http: AsyncClient) -> None:
    boss, mia, other = await team(http)
    label = (await http.post("/labels", json={"name": "urgent"}, headers=boss)).json()["id"]
    foreign = (await http.post("/labels", json={"name": "theirs"}, headers=other)).json()["id"]

    ok = await http.post("/tasks", json={"title": "t", "labels": [label]}, headers=mia)
    assert ok.status_code == 201, ok.text
    fetched = (await http.get(f"/tasks/{ok.json()['id']}", headers=mia)).json()
    assert [x["id"] if isinstance(x, dict) else x for x in fetched["labels"]] == [label]
    # a label from another organisation must not be attachable
    bad = await http.post("/tasks", json={"title": "t", "labels": [foreign]}, headers=mia)
    assert bad.status_code == 422, bad.text
    # members cannot create labels (no policy allows Label.create for them)
    assert (await http.post("/labels", json={"name": "x"}, headers=mia)).status_code == 403
