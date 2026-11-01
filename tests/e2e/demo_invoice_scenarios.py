"""Owner demo, invoice approval (generated project `demo_invoice`). Copied into the project's tests/ folder by
tests/e2e/test_cycle1_demo.py and run against a real Postgres. Every `say()` line goes to the transcript.

What the story shows: a clerk files invoices; a small invoice close to its purchase order is approved by the
rules alone; a large one waits for the right person; the `match_invoice` hook can refuse a submission; every
change of amount is kept with who and when; invoice numbers come from a gapless sequence; settings and the
status list are editable by the right roles only.
"""

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from tests._auth_support import outbox, sign_in  # noqa: F401

from app.db import session_factory
from app.main import app
from app.runtime_config import sequences

TRANSCRIPT = Path(__file__).resolve().parent.parent / "demo_transcript.log"


def say(line: str) -> None:
    with TRANSCRIPT.open("a", encoding="utf-8") as out:
        out.write(line + "\n")


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


async def next_number() -> str:
    async with session_factory() as session:
        number = await sequences.next_number(session, "invoice_no")
        await session.commit()
        return number


async def supplier(http: AsyncClient, who: dict[str, str]) -> str:
    response = await http.post(
        "/suppliers", json={"name": "Acme Parts", "email": "billing@acme.example", "payment_terms": "Net 30"}, headers=who
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def file_invoice(http, who, supplier_id, amount, po, number=None) -> str:  # noqa: ANN001
    response = await http.post(
        "/invoices",
        json={"invoice_no": number or await next_number(), "amount": amount, "po_amount": po, "supplier_id": supplier_id},
        headers=who,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    say(f"  clerk files {body['invoice_no']}: amount {amount}, purchase order {po} -> status {body['status']}")
    return body["id"]


async def move(http, who, invoice, name):  # noqa: ANN001, ANN201
    return await http.post(f"/invoices/{invoice}/transitions/{name}", headers=who)


async def status_of(http, who, invoice) -> str:  # noqa: ANN001
    return (await http.get(f"/invoices/{invoice}", headers=who)).json()["status"]


async def test_a_small_matching_invoice_is_approved_by_the_rules(http, people) -> None:  # noqa: ANN001
    say("Scenario 1: small invoice close to its purchase order")
    sup = await supplier(http, people["clerk"])
    invoice = await file_invoice(http, people["clerk"], sup, "1000.00", "1010.00")
    moved = await move(http, people["clerk"], invoice, "submit")
    assert moved.status_code == 200, moved.text
    assert moved.json()["status"] == "approved"
    log = (await http.get(f"/invoices/{invoice}/state-history", headers=people["clerk"])).json()
    steps = [(h["transition"], h["to_state"], "automatic" if h["automatic"] else "by a person") for h in log]
    say(f"  clerk submits -> {moved.json()['status']}; state log: {steps}")
    assert [s[1] for s in steps] == ["draft", "submitted", "approved"] and steps[-1][2] == "automatic"


async def test_a_large_invoice_waits_for_the_right_person(http, people) -> None:  # noqa: ANN001
    say("Scenario 2: large invoices wait for people")
    sup = await supplier(http, people["clerk"])
    mid = await file_invoice(http, people["clerk"], sup, "20000.00", "20000.00")
    big = await file_invoice(http, people["clerk"], sup, "60000.00", "60000.00")
    for invoice in (mid, big):
        assert (await move(http, people["clerk"], invoice, "submit")).json()["status"] == "pending_approval"
    say("  both invoices wait in pending_approval after submit")
    assert (await move(http, people["clerk"], mid, "approve")).status_code == 403
    say("  clerk tries to approve -> 403 (wrong role)")
    ok = await move(http, people["approver"], mid, "approve")
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    say("  approver approves the 20,000 invoice -> approved")
    refused = await move(http, people["approver"], big, "approve")
    assert refused.status_code == 409 and refused.json()["code"] == "transition_refused"
    assert await status_of(http, people["admin"], big) == "pending_approval"
    say("  approver tries the 60,000 invoice -> 409 transition_refused (guard: amount <= 50000), nothing changed")
    done = await move(http, people["admin"], big, "approve_large")
    assert done.status_code == 200 and done.json()["status"] == "approved"
    say("  admin approves the 60,000 invoice -> approved")
    assert (await move(http, people["approver"], big, "pay")).status_code == 403
    paid = await move(http, people["admin"], big, "pay")
    assert paid.json()["status"] == "paid"
    say("  only admin may pay: approver 403, admin -> paid")


async def test_the_match_hook_can_refuse_a_submission(http, people) -> None:  # noqa: ANN001
    say("Scenario 3: the match_invoice hook (transition guard, fail closed)")
    sup = await supplier(http, people["clerk"])
    off = await file_invoice(http, people["clerk"], sup, "5000.00", "100.00")
    refused = await move(http, people["clerk"], off, "submit")
    assert refused.status_code == 409 and refused.json()["code"] == "transition_refused", refused.text
    assert await status_of(http, people["clerk"], off) == "draft"
    say(f"  invoice 50x its purchase order: submit -> 409 {refused.json()['code']}, status stays draft")
    blank = await http.post(
        "/invoices", json={"invoice_no": " ", "amount": "10.00", "po_amount": "10.00", "supplier_id": sup},
        headers=people["clerk"],
    )
    assert blank.status_code == 201
    refused_blank = await move(http, people["clerk"], blank.json()["id"], "submit")
    assert refused_blank.status_code == 409
    say("  blank invoice number: submit -> 409 transition_refused")


async def test_amount_changes_are_kept_with_who_and_when(http, people) -> None:  # noqa: ANN001
    say("Scenario 4: change history")
    sup = await supplier(http, people["clerk"])
    invoice = await file_invoice(http, people["clerk"], sup, "1000.00", "1000.00")
    patched = await http.patch(f"/invoices/{invoice}", json={"amount": "1200.00", "memo": "ignored by history"},
                               headers=people["admin"])
    assert patched.status_code == 200, patched.text
    assert (await http.get(f"/invoices/{invoice}/history", headers=people["clerk"])).status_code == 403
    rows = (await http.get(f"/invoices/{invoice}/history", headers=people["approver"])).json()
    changes = sorted((r["op"], r["field"], r["old_value"], r["new_value"]) for r in rows)
    say(f"  admin changes the amount; approver reads the history: {changes}")
    updates = [c for c in changes if c[0] == "update"]
    assert [(c[1], c[3]) for c in updates] == [("amount", '"1200.00"')]  # one audited field changed (old value is the stored scale)
    assert not any(c[1] == "memo" for c in changes)
    assert all(r["actor_id"] for r in rows if r["op"] == "update")
    say("  the memo (not audited) is not recorded; clerk cannot read the history (403)")


async def test_invoice_numbers_are_gapless_under_parallel_filing(http, people) -> None:  # noqa: ANN001
    say("Scenario 5: gapless invoice-number sequence")
    sup = await supplier(http, people["clerk"])
    numbers = await asyncio.gather(*(next_number() for _ in range(12)))
    assert sorted(numbers) == [f"INV-{n:05d}" for n in range(1, 13)]
    say(f"  12 parallel draws -> {min(numbers)} .. {max(numbers)}, no gap, no duplicate")
    async with session_factory() as session:
        burned = await sequences.next_number(session, "invoice_no")
        await session.rollback()
    after = await next_number()
    assert burned == after == "INV-00013"
    say(f"  a rolled-back draw ({burned}) burns nothing: the next committed number is {after}")
    invoice = await file_invoice(http, people["clerk"], sup, "10.00", "10.00", number="INV-00014")
    shown = (await http.get("/config/sequences", headers=people["admin"])).json()
    say(f"  admin sees the counter: {shown}")
    assert invoice


async def test_settings_and_lists_are_edited_by_their_roles(http, people) -> None:  # noqa: ANN001
    say("Scenario 6: runtime settings and the status list")
    put = lambda key, value, who: http.put(f"/config/settings/{key}", json={"value": value}, headers=who)  # noqa: E731
    seen = {s["key"]: s["value"] for s in (await http.get("/config/settings", headers=people["approver"])).json()}
    say(f"  approver reads settings: {seen}")
    assert seen["approval_threshold"] == 10000
    assert (await put("approval_threshold", 15000, people["clerk"])).status_code == 403
    assert (await put("approval_threshold", 15000, people["approver"])).status_code == 200
    assert (await put("approval_threshold", -1, people["approver"])).status_code == 422
    assert (await put("payment_grace_days", 7, people["approver"])).status_code == 403
    say("  approval_threshold: clerk 403, approver 200 (15000), -1 -> 422; payment_grace_days: approver 403")
    items = (await http.get("/config/lists/invoice_status", headers=people["clerk"])).json()["items"]
    assert [i["value"] for i in items][:2] == ["draft", "pending_approval"]
    changed = await http.put("/config/lists/invoice_status/items/pending_approval", json={"label": "In review"},
                             headers=people["admin"])
    assert changed.status_code == 200
    assert (await http.put("/config/lists/invoice_status/items/pending_approval", json={"label": "x"},
                           headers=people["clerk"])).status_code == 403
    say("  admin relabels 'pending_approval' as 'In review'; clerk cannot (403)")
