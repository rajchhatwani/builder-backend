"""Scenario tests for the generated `authz_abac` project (Tickets). Copied into the project's
tests/ folder by tests/e2e/test_authz_stack.py and run against a real Postgres.

Policies under test (see tests/fixtures/specs/authz_abac.json):
  see_own_department     read tickets of your department, or that you opened
  open_in_own_department create only for your own department
  edit_own_unfinished    update your own tickets while they are not closed
  admins_manage_everything  role admin: everything on Ticket
  closed_is_final        deny update / replace / delete of closed tickets, for everyone
  delete_from_office     delete your own priority <= 3 tickets, from 10/8 or 127/8 only
"""

import uuid

import pytest
from app.auth.authorize import PolicyBinding
from app.auth.models import AuthUser
from app.auth.policy import Context
from app.core.errors import AppError
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from tests._auth_support import client_for, outbox, sign_in  # noqa: F401

from app.db import session_factory
from app.main import app


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def person(
    http: AsyncClient, email: str, department: str | None, roles: list[str] | None = None
):  # noqa: ANN201
    headers = await sign_in(http, email, roles=roles if roles is not None else ["agent"])
    async with session_factory() as session:
        user = (await session.execute(select(AuthUser).where(AuthUser.email == email))).scalar_one()
        user.department = department
        await session.commit()
    return headers


def ticket(
    department: str = "support", status: str = "open", priority: int = 2, title: str = "t"
) -> dict:
    return {"title": title, "status": status, "priority": priority, "department": department}


async def open_ticket(http: AsyncClient, headers: dict, **kwargs) -> str:  # noqa: ANN003
    response = await http.post("/tickets", json=ticket(**kwargs), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_signed_out_is_refused(http: AsyncClient) -> None:
    assert (await http.get("/tickets")).status_code == 401
    assert (await http.post("/tickets", json=ticket())).status_code == 401


async def test_create_only_in_own_department(http: AsyncClient) -> None:
    alice = await person(http, "alice@example.com", "support")
    assert (await http.post("/tickets", json=ticket("support"), headers=alice)).status_code == 201
    refused = await http.post("/tickets", json=ticket("sales"), headers=alice)
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "forbidden"
    # and nothing was written
    assert (await http.get("/tickets", headers=alice)).json()["total"] == 1


async def test_reads_are_scoped_in_the_database_not_after_the_fact(http: AsyncClient) -> None:
    alice = await person(http, "alice@example.com", "support")
    bob = await person(http, "bob@example.com", "support")
    carol = await person(http, "carol@example.com", "sales")
    ids = [await open_ticket(http, alice, title=f"a{i}") for i in range(3)]
    await open_ticket(http, carol, department="sales", title="c")

    bob_list = (await http.get("/tickets", headers=bob)).json()
    assert bob_list["total"] == 3 and {t["id"] for t in bob_list["items"]} == set(ids)

    carol_list = (await http.get("/tickets", headers=carol)).json()
    assert carol_list["total"] == 1  # the total is computed under the same filter: no leak
    page = (await http.get("/tickets", params={"limit": 1, "offset": 0}, headers=carol)).json()
    assert page["total"] == 1 and len(page["items"]) == 1

    for tid in ids:
        assert (await http.get(f"/tickets/{tid}", headers=carol)).status_code == 404
        assert (await http.head(f"/tickets/{tid}", headers=carol)).status_code == 404
    assert (await http.get(f"/tickets/{ids[0]}", headers=bob)).status_code == 200


async def test_filters_cannot_widen_the_scope(http: AsyncClient) -> None:
    alice = await person(http, "alice@example.com", "support")
    carol = await person(http, "carol@example.com", "sales")
    await open_ticket(http, alice)
    result = await http.get("/tickets", params={"status": "open"}, headers=carol)
    assert result.json()["total"] == 0


async def test_only_the_author_edits_and_only_while_unfinished(http: AsyncClient) -> None:
    alice = await person(http, "alice@example.com", "support")
    bob = await person(http, "bob@example.com", "support")
    tid = await open_ticket(http, alice)

    # Bob can read it but no policy lets him change it: it is not even a row he can update
    assert (
        await http.patch(f"/tickets/{tid}", json={"title": "mine now"}, headers=bob)
    ).status_code == 404
    assert (
        await http.patch(f"/tickets/{tid}", json={"title": "better"}, headers=alice)
    ).status_code == 200

    # Alice closes her ticket; from then on nobody can touch it ("deny wins")
    assert (
        await http.patch(f"/tickets/{tid}", json={"status": "closed"}, headers=alice)
    ).status_code == 200
    assert (
        await http.patch(f"/tickets/{tid}", json={"title": "reopen?"}, headers=alice)
    ).status_code == 404
    assert (await http.delete(f"/tickets/{tid}", headers=alice)).status_code == 404


async def test_admin_role_sees_and_changes_everything_except_closed(http: AsyncClient) -> None:
    alice = await person(http, "alice@example.com", "support")
    carol = await person(http, "carol@example.com", "sales")
    boss = await person(http, "boss@example.com", None, roles=["admin"])
    a = await open_ticket(http, alice)
    c = await open_ticket(http, carol, department="sales")
    assert (await http.get("/tickets", headers=boss)).json()["total"] == 2
    assert (
        await http.patch(f"/tickets/{c}", json={"title": "boss was here"}, headers=boss)
    ).status_code == 200
    created = await http.post("/tickets", json=ticket("legal"), headers=boss)  # any department
    assert created.status_code == 201
    assert (
        await http.patch(f"/tickets/{a}", json={"status": "closed"}, headers=boss)
    ).status_code == 200
    assert (
        await http.patch(f"/tickets/{a}", json={"title": "x"}, headers=boss)
    ).status_code == 404  # even admins


async def test_delete_needs_ownership_priority_and_the_office_network(http: AsyncClient) -> None:
    alice = await person(http, "alice@example.com", "support")
    bob = await person(http, "bob@example.com", "support")
    low = await open_ticket(http, alice, priority=2)
    high = await open_ticket(http, alice, priority=5)
    assert (await http.delete(f"/tickets/{low}", headers=bob)).status_code == 404  # not his
    assert (
        await http.delete(f"/tickets/{high}", headers=alice)
    ).status_code == 404  # priority too high
    assert (await http.delete(f"/tickets/{low}", headers=alice)).status_code == 204

    elsewhere = AsyncClient(
        transport=ASGITransport(app=app, client=("8.8.8.8", 1)), base_url="http://test"
    )
    async with elsewhere:
        other = await open_ticket(http, alice, priority=1)
        refused = await elsewhere.delete(f"/tickets/{other}", headers=alice)
        assert refused.status_code == 403, refused.text  # the address alone rules it out
    assert (await http.delete(f"/tickets/{other}", headers=alice)).status_code == 204


async def test_a_change_cannot_move_a_row_out_of_the_callers_reach(http: AsyncClient) -> None:
    """Exercise the write-time check directly: the person could not read the changed row."""
    subject = {"id": uuid.uuid4(), "roles": ("agent",), "department": "support"}
    binding = PolicyBinding("Ticket", "update", Context(subject=subject, env={}))
    binding.check_changed_row(
        {"department": "support", "created_by_id": uuid.uuid4()}
    )  # still readable
    with pytest.raises(AppError) as refused:
        binding.check_changed_row({"department": "sales", "created_by_id": uuid.uuid4()})
    assert refused.value.status_code == 403
    binding.check_changed_row(
        {"department": "sales", "created_by_id": subject["id"]}
    )  # own: still readable


async def test_missing_attribute_means_no_access(http: AsyncClient) -> None:
    nobody = await person(http, "nobody@example.com", None)  # no department at all
    assert (await http.post("/tickets", json=ticket("support"), headers=nobody)).status_code == 403
    assert (await http.get("/tickets", headers=nobody)).json()["total"] == 0
