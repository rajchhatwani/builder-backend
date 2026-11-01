"""Scenario tests for the generated `flow_abac` project (tickets with a state machine, abac policies).
Copied into the project's tests/ folder by tests/e2e/test_state_machine_stack.py, run on a real Postgres.

Rules under test: a move is a change, so on a policy entity the caller must pass the UPDATE policy as well
as the read policy. A same-department peer who may read a ticket but not edit it cannot move it; nobody can
reopen a closed ticket (closed_is_final denies update); a guard that errors refuses the move (fail closed).
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from tests._auth_support import outbox, sign_in  # noqa: F401

from app.auth.models import AuthUser
from app.db import session_factory
from app.main import app


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def person(http: AsyncClient, email: str, department: str, roles: list[str]):  # noqa: ANN201
    headers = await sign_in(http, email, roles=roles)
    async with session_factory() as session:
        user = (await session.execute(select(AuthUser).where(AuthUser.email == email))).scalar_one()
        user.department = department
        await session.commit()
    return headers


@pytest.fixture
async def people(http: AsyncClient) -> dict[str, dict[str, str]]:
    return {
        "alice": await person(http, "alice@example.com", "support", ["agent"]),
        "bob": await person(http, "bob@example.com", "support", ["agent"]),  # same department peer
        "carol": await person(http, "carol@example.com", "sales", ["agent"]),
        "admin": await person(http, "admin@example.com", "support", ["admin"]),
    }


async def open_ticket(http: AsyncClient, who: dict[str, str]) -> str:
    response = await http.post(
        "/tickets",
        json={"title": "t", "status": "closed", "priority": 2, "department": "support"},
        headers=who,
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "open"
    return response.json()["id"]


async def move(http: AsyncClient, who: dict[str, str], ticket: str, name: str):  # noqa: ANN201
    return await http.post(f"/tickets/{ticket}/transitions/{name}", headers=who)


async def status(http: AsyncClient, who: dict[str, str], ticket: str) -> str:
    return (await http.get(f"/tickets/{ticket}", headers=who)).json()["status"]


async def test_a_peer_who_cannot_edit_cannot_move(http, people) -> None:  # noqa: ANN001
    ticket = await open_ticket(http, people["alice"])
    assert (await http.get(f"/tickets/{ticket}", headers=people["bob"])).status_code == 200  # may read
    patched = await http.patch(f"/tickets/{ticket}", json={"title": "x"}, headers=people["bob"])
    assert patched.status_code in (403, 404), patched.text
    refused = await move(http, people["bob"], ticket, "start")
    assert refused.status_code in (403, 404), refused.text
    assert await status(http, people["alice"], ticket) == "open"  # nothing moved
    history = (await http.get(f"/tickets/{ticket}/state-history", headers=people["alice"])).json()
    assert [h["transition"] for h in history] == ["created"]
    # reading what could be done is still allowed to a reader
    assert (await http.get(f"/tickets/{ticket}/transitions", headers=people["bob"])).status_code == 200
    # another department cannot even see the ticket
    assert (await move(http, people["carol"], ticket, "start")).status_code in (403, 404)


async def test_the_author_and_an_admin_can_move(http, people) -> None:  # noqa: ANN001
    ticket = await open_ticket(http, people["alice"])
    moved = await move(http, people["alice"], ticket, "start")
    assert moved.status_code == 200, moved.text
    assert moved.json()["status"] == "pending"
    other = await open_ticket(http, people["alice"])
    assert (await move(http, people["admin"], other, "close")).json()["status"] == "closed"


async def test_a_closed_ticket_cannot_be_reopened_by_anyone(http, people) -> None:  # noqa: ANN001
    ticket = await open_ticket(http, people["alice"])
    assert (await move(http, people["alice"], ticket, "close")).json()["status"] == "closed"
    for who in ("bob", "alice", "admin", "carol"):
        refused = await move(http, people[who], ticket, "reopen")
        assert refused.status_code in (403, 404), (who, refused.text)
    assert await status(http, people["alice"], ticket) == "closed"
    history = (await http.get(f"/tickets/{ticket}/state-history", headers=people["alice"])).json()
    assert [h["transition"] for h in history] == ["created", "close"]


async def test_a_peer_cannot_close_then_reopen(http, people) -> None:  # noqa: ANN001
    ticket = await open_ticket(http, people["alice"])
    assert (await move(http, people["bob"], ticket, "close")).status_code in (403, 404)
    assert (await move(http, people["bob"], ticket, "reopen")).status_code in (403, 404)
    assert await status(http, people["alice"], ticket) == "open"


@pytest.mark.parametrize("name", ["escalate", "overflow"])
async def test_a_guard_that_errors_refuses_the_move(http, people, name) -> None:  # noqa: ANN001
    """`div(1, priority - priority)` divides by zero and `priority * 9223372036854775807` overflows:
    both must fail closed (409, nothing changed), never let the move through and never a 500."""
    ticket = await open_ticket(http, people["alice"])
    refused = await move(http, people["alice"], ticket, name)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "transition_refused"
    assert await status(http, people["alice"], ticket) == "open"
    listing = {t["name"]: t for t in (await http.get(f"/tickets/{ticket}/transitions", headers=people["alice"])).json()}
    assert listing[name]["allowed"] is False and listing[name]["refused_because"] == "guard"
