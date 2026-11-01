"""Scenario tests for the generated `flow_invoices` project (invoice approval). Copied into the project's
tests/ folder by tests/e2e/test_state_machine_stack.py and run against a real Postgres.

Rules under test: a clerk submits; small invoices close to their purchase order are approved
automatically; the rest wait for an approver (up to 50,000) or an admin (any amount); only an admin pays.
"""

import asyncio

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
        "clerk": await sign_in(http, "clerk@example.com", roles=["clerk"], n=0),
        "approver": await sign_in(http, "approver@example.com", roles=["approver"], n=1),
        "admin": await sign_in(http, "admin@example.com", roles=["admin"], n=2),
    }


async def make(http: AsyncClient, who: dict[str, str], amount: str, po: str) -> str:
    response = await http.post(
        "/invoices",
        json={"invoice_no": "INV-1", "amount": amount, "po_amount": po, "status": "paid"},
        headers=who,
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "draft"  # the caller's "paid" is ignored
    return response.json()["id"]


async def move(http: AsyncClient, who: dict[str, str], invoice: str, name: str):  # noqa: ANN201
    return await http.post(f"/invoices/{invoice}/transitions/{name}", headers=who)


async def status(http: AsyncClient, who: dict[str, str], invoice: str) -> str:
    return (await http.get(f"/invoices/{invoice}", headers=who)).json()["status"]


async def test_a_small_invoice_near_its_po_is_approved_automatically(http, people) -> None:  # noqa: ANN001
    invoice = await make(http, people["clerk"], "1000.00", "1010.00")
    moved = await move(http, people["clerk"], invoice, "submit")
    assert moved.status_code == 200, moved.text
    assert moved.json()["status"] == "approved"  # submit + automatic approval, one request
    history = (await http.get(f"/invoices/{invoice}/state-history", headers=people["clerk"])).json()
    assert [(h["transition"], h["to_state"], h["automatic"]) for h in history] == [
        ("created", "draft", False),
        ("submit", "submitted", False),
        ("auto_approve", "approved", True),
    ]
    assert history[1]["actor_id"] is not None and history[2]["actor_id"] is None


async def test_a_variance_or_a_large_amount_waits_for_a_person(http, people) -> None:  # noqa: ANN001
    far_from_po = await make(http, people["clerk"], "1000.00", "900.00")
    large = await make(http, people["clerk"], "20000.00", "20000.00")
    for invoice in (far_from_po, large):
        assert (await move(http, people["clerk"], invoice, "submit")).json()["status"] == "pending_approval"


async def test_roles_and_guards_decide_who_may_approve(http, people) -> None:  # noqa: ANN001
    invoice = await make(http, people["clerk"], "60000.00", "60000.00")
    await move(http, people["clerk"], invoice, "submit")
    assert await status(http, people["clerk"], invoice) == "pending_approval"

    assert (await move(http, people["clerk"], invoice, "approve")).status_code == 403  # wrong role
    refused = await move(http, people["approver"], invoice, "approve")  # right role, guard amount <= 50000
    assert refused.status_code == 409 and refused.json()["code"] == "transition_refused"
    assert await status(http, people["admin"], invoice) == "pending_approval"  # nothing changed

    listing = (await http.get(f"/invoices/{invoice}/transitions", headers=people["approver"])).json()
    by_name = {t["name"]: t for t in listing}
    assert by_name["approve"] == {
        "name": "approve", "to_state": "approved", "allowed": False, "refused_because": "guard",
    }
    assert by_name["approve_large"]["refused_because"] == "role"

    assert (await move(http, people["admin"], invoice, "approve_large")).json()["status"] == "approved"
    assert (await move(http, people["clerk"], invoice, "pay")).status_code == 403
    assert (await move(http, people["admin"], invoice, "pay")).json()["status"] == "paid"


async def test_moves_out_of_the_wrong_state_and_unknown_moves_fail(http, people) -> None:  # noqa: ANN001
    invoice = await make(http, people["clerk"], "100.00", "100.00")
    wrong = await move(http, people["admin"], invoice, "pay")
    assert wrong.status_code == 409 and wrong.json()["code"] == "invalid_transition"
    auto = await move(http, people["admin"], invoice, "auto_approve")  # automatic ones are not callable
    assert auto.status_code == 404
    assert (await move(http, people["admin"], invoice, "nope")).status_code == 404


async def test_the_state_cannot_be_edited_directly(http, people) -> None:  # noqa: ANN001
    invoice = await make(http, people["clerk"], "100.00", "100.00")
    patched = await http.patch(f"/invoices/{invoice}", json={"status": "paid"}, headers=people["admin"])
    assert patched.status_code == 200 and patched.json()["status"] == "draft"


async def test_the_role_is_checked_before_the_state(http, people) -> None:  # noqa: ANN001
    invoice = await make(http, people["clerk"], "100.00", "100.00")  # draft: `pay` cannot start here
    # a caller who may not pay learns nothing about the state: 403, not 409
    assert (await move(http, people["clerk"], invoice, "pay")).status_code == 403
    assert (await move(http, people["admin"], invoice, "pay")).status_code == 409


async def test_many_simultaneous_moves_have_exactly_one_winner(http, people) -> None:  # noqa: ANN001
    """12 callers race for one record, 5 times over: the row lock lets exactly one of them through."""
    for _round in range(5):
        invoice = await make(http, people["clerk"], "60000.00", "60000.00")
        await move(http, people["clerk"], invoice, "submit")
        calls = [
            move(http, people["admin"] if i % 2 == 0 else people["approver"], invoice,
                 "approve_large" if i % 4 == 0 else "reject")
            for i in range(12)
        ]
        # approve_large is admin-only: the approvers' reject and the admins' approve_large compete
        results = await asyncio.gather(*calls)
        codes = [r.status_code for r in results]
        assert codes.count(200) == 1, codes
        assert all(c in (200, 403, 409) for c in codes), codes
        history = (await http.get(f"/invoices/{invoice}/state-history", headers=people["admin"])).json()
        assert len([h for h in history if h["from_state"] == "pending_approval"]) == 1


async def test_a_transition_without_roles_needs_the_right_to_update_the_invoice(http, people) -> None:  # noqa: ANN001
    # `withdraw` lists no roles: it is open to whoever may UPDATE an invoice (admin only), not to every reader.
    invoice = await make(http, people["clerk"], "100.00", "100.00")
    for reader in ("clerk", "approver"):  # both may read the invoice, neither may update it
        assert (await http.get(f"/invoices/{invoice}", headers=people[reader])).status_code == 200
        refused = await move(http, people[reader], invoice, "withdraw")
        assert refused.status_code == 403, refused.text
    assert await status(http, people["admin"], invoice) == "draft"
    anonymous = await http.post(f"/invoices/{invoice}/transitions/withdraw")
    assert anonymous.status_code == 401
    moved = await move(http, people["admin"], invoice, "withdraw")
    assert moved.status_code == 200 and moved.json()["status"] == "withdrawn"
    # a transition that lists roles is unchanged: the clerk submits without being able to update
    other = await make(http, people["clerk"], "100.00", "100.00")
    assert (await move(http, people["clerk"], other, "submit")).status_code == 200
