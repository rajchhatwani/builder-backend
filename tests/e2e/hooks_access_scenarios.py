"""Scenario tests for the generated `hooks-access` project (role permissions, owner rows, tenants).
Copied into the project's tests/ folder by tests/e2e/test_hooks_stack.py and run on a real Postgres.

Rule under test (SENTINEL M-3): `find_rows` is not a back door. A hook that declares `reads` sees exactly the
rows and fields the entity's own list endpoint shows the person whose request runs the hook:
  * a member sees their own notes only, an admin all notes of the tenant, nobody another tenant's rows;
  * an entity the person may not list (Ledger for a member) is refused with AccessDenied, no rows;
  * with no identifiable person (system write) the read is refused;
  * only the fields of the Read schema come back, and a hidden column cannot be filtered on.
"""

import importlib
from collections.abc import Callable
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from tests._auth_support import outbox, sign_in  # noqa: F401

from app.hooks_gen import contracts, registry, runtime
from app.main import app
from app.schemas.notes import NoteRead

sdk = importlib.import_module("app.platform_sdk")


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def world(http: AsyncClient) -> dict[str, dict[str, str]]:
    """Tenant A: boss (admin) and mia (member). Tenant B: other (admin). Each wrote one note, the
    admins one ledger entry."""
    people = {
        "boss": await sign_in(http, "boss@example.com", roles=["admin"], n=0),
        "mia": await sign_in(http, "mia@example.com", roles=["member"], n=1, join="boss@example.com"),
        "other": await sign_in(http, "other@example.com", roles=["admin"], n=2),
    }
    for who, title in (("boss", "boss-note"), ("mia", "mia-note"), ("other", "other-note")):
        made = await http.post("/notes", json={"title": title}, headers=people[who])
        assert made.status_code == 201, made.text
    for who, label in (("boss", "ledger-a"), ("other", "ledger-b")):
        made = await http.post("/ledgers", json={"label": label}, headers=people[who])
        assert made.status_code == 201, made.text
    return people


async def peek(
    http: AsyncClient, monkeypatch: pytest.MonkeyPatch, who: dict[str, str], probe: Callable[[], Any]
) -> Any:
    """Create a note as `who` (the after_commit hook runs for them) and return what `probe` saw inside it."""
    box: list[Any] = []

    def fn(data):  # noqa: ANN001, ANN202
        try:
            box.append(probe())
        except Exception as exc:  # noqa: BLE001
            box.append(exc)
        return contracts.PeekResult(seen=True)

    monkeypatch.setitem(registry.HOOKS["peek"], "fn", fn)
    made = await http.post("/notes", json={"title": "trigger"}, headers=who)
    assert made.status_code == 201, made.text
    assert len(box) == 1
    return box[0]


def titles(rows: list[dict[str, Any]]) -> set[str]:
    return {row["title"] for row in rows}


async def test_a_member_sees_only_their_own_notes(http, world, monkeypatch) -> None:  # noqa: ANN001
    rows = await peek(http, monkeypatch, world["mia"], lambda: sdk.find_rows("Note", limit=20))
    assert titles(rows) == {"mia-note", "trigger"}  # not boss-note (owner rule), not other-note (tenant)
    listed = (await http.get("/notes", headers=world["mia"])).json()["items"]
    assert {str(r["id"]) for r in rows} == {r["id"] for r in listed}  # exactly what the endpoint shows


async def test_an_admin_sees_the_tenant_and_nothing_beyond(http, world, monkeypatch) -> None:  # noqa: ANN001
    rows = await peek(http, monkeypatch, world["boss"], lambda: sdk.find_rows("Note", limit=20))
    assert titles(rows) == {"boss-note", "mia-note", "trigger"}  # unrestricted within the tenant
    assert "other-note" not in titles(rows)  # tenant isolation
    listed = (await http.get("/notes", headers=world["boss"])).json()["items"]
    assert {str(r["id"]) for r in rows} == {r["id"] for r in listed}
    other = await peek(http, monkeypatch, world["other"], lambda: sdk.find_rows("Note", limit=20))
    assert titles(other) == {"other-note", "trigger"}


async def test_filters_cannot_reach_rows_outside_the_access_rules(http, world, monkeypatch) -> None:  # noqa: ANN001
    rows = await peek(http, monkeypatch, world["mia"], lambda: sdk.find_rows("Note", limit=20, title="boss-note"))
    assert rows == []
    rows = await peek(http, monkeypatch, world["mia"], lambda: sdk.find_rows("Note", limit=20, title="other-note"))
    assert rows == []
    rows = await peek(http, monkeypatch, world["boss"], lambda: sdk.find_rows("Note", limit=20, title="mia-note"))
    assert titles(rows) == {"mia-note"}


async def test_an_entity_the_person_may_not_list_is_refused(http, world, monkeypatch) -> None:  # noqa: ANN001
    refused = await peek(http, monkeypatch, world["mia"], lambda: sdk.find_rows("Ledger", limit=20))
    assert isinstance(refused, Exception) and type(refused).__name__ == "AccessDenied"
    assert "ledger" not in str(refused).lower() and "ledger-a" not in str(refused)
    assert (await http.get("/ledgers", headers=world["mia"])).status_code == 403  # the endpoint agrees


async def test_an_allowed_entity_is_tenant_scoped_too(http, world, monkeypatch) -> None:  # noqa: ANN001
    rows = await peek(http, monkeypatch, world["boss"], lambda: sdk.find_rows("Ledger", limit=20))
    assert {r["label"] for r in rows} == {"ledger-a"}
    rows = await peek(http, monkeypatch, world["other"], lambda: sdk.find_rows("Ledger", limit=20))
    assert {r["label"] for r in rows} == {"ledger-b"}


async def test_only_the_fields_of_the_read_schema_come_back(http, world, monkeypatch) -> None:  # noqa: ANN001
    rows = await peek(http, monkeypatch, world["boss"], lambda: sdk.find_rows("Note", limit=20))
    assert rows and all(set(row) <= set(NoteRead.model_fields) for row in rows)
    assert all("tenant_id" not in row and "created_by_id" not in row for row in rows)
    # a column the endpoint does not return cannot be used as a filter either (no oracle)
    hidden = await peek(http, monkeypatch, world["boss"], lambda: sdk.find_rows("Note", limit=20, tenant_id="x"))
    assert isinstance(hidden, ValueError)


async def test_without_a_signed_in_person_nothing_is_read(http, world, monkeypatch) -> None:  # noqa: ANN001
    outcome: list[Any] = []

    def fn(data):  # noqa: ANN001, ANN202
        try:
            outcome.append(sdk.find_rows("Note", limit=20))
        except Exception as exc:  # noqa: BLE001
            outcome.append(exc)
        return contracts.PeekResult(seen=True)

    monkeypatch.setitem(registry.HOOKS["peek"], "fn", fn)
    await runtime.call(registry.HOOKS["peek"], {"id": "00000000-0000-4000-8000-000000000001", "title": "t"}, None)
    assert len(outcome) == 1 and type(outcome[0]).__name__ == "AccessDenied"


async def test_a_caller_without_a_tenant_reads_nothing(http, world, monkeypatch) -> None:  # noqa: ANN001
    class Stray:
        id = "00000000-0000-4000-8000-000000000002"
        roles = ["admin"]
        tenant_id = None

    outcome: list[Any] = []

    def fn(data):  # noqa: ANN001, ANN202
        try:
            outcome.append(sdk.find_rows("Note", limit=20))
        except Exception as exc:  # noqa: BLE001
            outcome.append(exc)
        return contracts.PeekResult(seen=True)

    monkeypatch.setitem(registry.HOOKS["peek"], "fn", fn)
    await runtime.call(registry.HOOKS["peek"], {"id": "00000000-0000-4000-8000-000000000001", "title": "t"}, Stray())
    assert len(outcome) == 1 and type(outcome[0]).__name__ == "AccessDenied"


async def test_a_hook_still_cannot_read_what_it_did_not_declare(http, world, monkeypatch) -> None:  # noqa: ANN001
    rows = await peek(http, monkeypatch, world["boss"], lambda: sdk.find_rows("AuthUser", limit=20))
    assert type(rows).__name__ == "BudgetExceeded"
