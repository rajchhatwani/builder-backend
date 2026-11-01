"""Scenario tests for the generated `hooks-access-abac` project (attribute policies).
Copied into the project's tests/ folder by tests/e2e/test_hooks_stack.py and run on a real Postgres.

Rule under test (SENTINEL M-3): under an abac policy set `find_rows` applies the same policy decision
as GET /tickets: a person sees the tickets of their own department and the ones they opened, an admin
everything, and the read is refused when no policy allows listing at all.
"""

import importlib
from collections.abc import Callable
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from tests._auth_support import outbox, sign_in  # noqa: F401

from app.auth import authorize
from app.auth.models import AuthUser
from app.auth.policy_data import POLICY_DATA
from sqlalchemy import select

from app.db import session_factory
from app.hooks_gen import contracts, registry, runtime
from app.main import app

sdk = importlib.import_module("app.platform_sdk")


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def person(http: AsyncClient, email: str, department: str, roles: list[str], n: int) -> dict[str, str]:
    headers = await sign_in(http, email, roles=roles, n=n)
    async with session_factory() as session:
        user = (await session.execute(select(AuthUser).where(AuthUser.email == email))).scalar_one()
        user.department = department
        await session.commit()
    return headers


async def ticket(http: AsyncClient, who: dict[str, str], title: str, department: str) -> None:
    made = await http.post(
        "/tickets",
        json={"title": title, "status": "open", "priority": 1, "department": department},
        headers=who,
    )
    assert made.status_code == 201, made.text


@pytest.fixture
async def world(http: AsyncClient) -> dict[str, dict[str, str]]:
    people = {
        "ann": await person(http, "ann@example.com", "sales", ["agent"], 0),
        "bob": await person(http, "bob@example.com", "support", ["agent"], 1),
        "root": await person(http, "root@example.com", "it", ["admin"], 2),
    }
    await ticket(http, people["ann"], "ann-sales", "sales")
    await ticket(http, people["bob"], "bob-support", "support")
    return people


async def peek(
    http: AsyncClient, monkeypatch: pytest.MonkeyPatch, who: dict[str, str], probe: Callable[[], Any], department: str
) -> Any:
    box: list[Any] = []

    def fn(data):  # noqa: ANN001, ANN202
        try:
            box.append(probe())
        except Exception as exc:  # noqa: BLE001
            box.append(exc)
        return contracts.PeekResult(seen=True)

    monkeypatch.setitem(registry.HOOKS["peek"], "fn", fn)
    await ticket(http, who, "trigger", department)
    assert len(box) == 1
    return box[0]


async def test_the_hook_sees_what_the_policy_shows_the_person(http, world, monkeypatch) -> None:  # noqa: ANN001
    rows = await peek(http, monkeypatch, world["ann"], lambda: sdk.find_rows("Ticket", limit=20), "sales")
    assert {r["title"] for r in rows} == {"ann-sales", "trigger"}  # not bob-support
    listed = (await http.get("/tickets", headers=world["ann"])).json()["items"]
    assert {str(r["id"]) for r in rows} == {r["id"] for r in listed}


async def test_an_admin_is_unrestricted(http, world, monkeypatch) -> None:  # noqa: ANN001
    rows = await peek(http, monkeypatch, world["root"], lambda: sdk.find_rows("Ticket", limit=20), "it")
    assert {r["title"] for r in rows} == {"ann-sales", "bob-support", "trigger"}


async def test_a_filter_cannot_pull_a_forbidden_row(http, world, monkeypatch) -> None:  # noqa: ANN001
    rows = await peek(http, monkeypatch, world["bob"], lambda: sdk.find_rows("Ticket", limit=20, title="ann-sales"), "support")
    assert rows == []


async def test_a_person_no_policy_allows_to_list_is_refused(http, world, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(authorize, "POLICY_SET", authorize.load_policy_set({**POLICY_DATA, "policies": {}, "attachments": {}}))
    outcome: list[Any] = []

    def fn(data):  # noqa: ANN001, ANN202
        try:
            outcome.append(sdk.find_rows("Ticket", limit=20))
        except Exception as exc:  # noqa: BLE001
            outcome.append(exc)
        return contracts.PeekResult(seen=True)

    monkeypatch.setitem(registry.HOOKS["peek"], "fn", fn)
    class Caller:
        id = "00000000-0000-4000-8000-000000000003"
        email = "x@example.com"
        roles = ["agent"]
        tenant_id = None

    await runtime.call(registry.HOOKS["peek"], {"id": "00000000-0000-4000-8000-000000000001", "title": "t"}, Caller())
    assert len(outcome) == 1 and type(outcome[0]).__name__ == "AccessDenied"


async def test_without_a_signed_in_person_nothing_is_read(http, world, monkeypatch) -> None:  # noqa: ANN001
    outcome: list[Any] = []

    def fn(data):  # noqa: ANN001, ANN202
        try:
            outcome.append(sdk.find_rows("Ticket", limit=20))
        except Exception as exc:  # noqa: BLE001
            outcome.append(exc)
        return contracts.PeekResult(seen=True)

    monkeypatch.setitem(registry.HOOKS["peek"], "fn", fn)
    await runtime.call(registry.HOOKS["peek"], {"id": "00000000-0000-4000-8000-000000000001", "title": "t"}, None)
    assert len(outcome) == 1 and type(outcome[0]).__name__ == "AccessDenied"
