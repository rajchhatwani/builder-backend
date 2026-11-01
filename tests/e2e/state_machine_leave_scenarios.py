"""Scenario tests for the generated `flow_leave` project (HR leave request). Copied into the project's
tests/ folder by tests/e2e/test_state_machine_stack.py and run against a real Postgres.

Rules under test: a request is routed on creation (short -> manager, long -> HR, more days than the
balance -> declined); only the matching reviewer decides; the employee or HR can cancel before a decision.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from tests._auth_support import outbox, sign_in  # noqa: F401

from app.main import app


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def people(http: AsyncClient) -> dict[str, dict[str, str]]:
    return {
        "employee": await sign_in(http, "emp@example.com", roles=["employee"], n=0),
        "manager": await sign_in(http, "mgr@example.com", roles=["manager"], n=1),
        "hr": await sign_in(http, "hr@example.com", roles=["hr"], n=2),
    }


async def request(http: AsyncClient, who: dict[str, str], days: int, balance: int) -> dict:
    response = await http.post(
        "/leave_requests", json={"employee": "Sam", "days": days, "balance": balance}, headers=who
    )
    assert response.status_code == 201, response.text
    return response.json()


async def move(http: AsyncClient, who: dict[str, str], item: str, name: str):  # noqa: ANN201
    return await http.post(f"/leave_requests/{item}/transitions/{name}", headers=who)


async def test_requests_are_routed_when_they_are_created(http, people) -> None:  # noqa: ANN001
    short = await request(http, people["employee"], 3, 10)
    long_ = await request(http, people["employee"], 8, 10)
    over = await request(http, people["employee"], 12, 10)
    assert (short["state"], long_["state"], over["state"]) == ("manager_review", "hr_review", "declined")
    history = (await http.get(f"/leave_requests/{over['id']}/state-history", headers=people["hr"])).json()
    assert [h["to_state"] for h in history] == ["requested", "declined"]
    assert history[1]["automatic"] is True


async def test_only_the_matching_reviewer_decides(http, people) -> None:  # noqa: ANN001
    short = await request(http, people["employee"], 3, 10)
    long_ = await request(http, people["employee"], 8, 10)
    assert (await move(http, people["hr"], short["id"], "manager_approve")).status_code == 403
    assert (await move(http, people["manager"], long_["id"], "manager_approve")).status_code == 409
    assert (await move(http, people["manager"], long_["id"], "hr_approve")).status_code == 403
    assert (await move(http, people["manager"], short["id"], "manager_approve")).json()["state"] == "approved"
    assert (await move(http, people["hr"], long_["id"], "hr_decline")).json()["state"] == "declined"
    # decided requests are final
    assert (await move(http, people["employee"], short["id"], "cancel")).status_code == 409


async def test_the_employee_can_cancel_before_a_decision(http, people) -> None:  # noqa: ANN001
    item = await request(http, people["employee"], 2, 10)
    assert (await move(http, people["manager"], item["id"], "cancel")).status_code == 403
    cancelled = await move(http, people["employee"], item["id"], "cancel")
    assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled"
