"""Scenario tests for the AI pack, documents block (D34) in the generated `ai_documents_knowledge` project (copied into the
project's tests/ by tests/e2e/test_ai_documents_stack.py, run against a real Postgres). FAKE provider only.

Spec: kinds invoice (vendor, total required, due_date) and receipt (merchant, amount both required); stage extract
(fake-small); review_below_bp 8000; upload agent/customer, review admin, read agent; multi-tenant; budget 5 USD per day.
Proves: extraction through the gateway (ledger row, linked by call_id, usage endpoint), anchors really point into the text
(also across form-feed pages), a lying model (quote does not match, offsets out of range, bad confidence) goes to review with
confidence 0, the review threshold edge (7999 / 8000), missing required fields, correct / approve / reject, 8 parallel
decisions give exactly one winner, own-only reads for uploaders, tenant isolation, idempotent create, no 500 anywhere."""

import asyncio
import json

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient, Response

from app.ai import config as ai_config
from app.db import session_factory
from app.main import app
from tests._auth_support import outbox, sign_in  # noqa: F401

DOC = "INVOICE 4411\nvendor: Acme Corp\ntotal: 1250.00\ndue date: 2026-12-01\n"


@pytest.fixture(autouse=True)
def _fake_directives(monkeypatch) -> None:  # noqa: ANN001
    """Generated code ignores [[fake:...]] / [[conf=...]] markers by default (text is untrusted); most scenarios drive the fake with them."""
    monkeypatch.setattr(ai_config, "FAKE_DIRECTIVES", True)


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def people(http: AsyncClient) -> dict[str, dict[str, str]]:
    return {
        "admin": await sign_in(http, "a@example.com", roles=["admin"], n=0),
        "agent": await sign_in(http, "a_agent@example.com", roles=["agent"], n=1, join="a@example.com"),
        "customer": await sign_in(http, "a_c@example.com", roles=["customer"], n=2, join="a@example.com"),
        "customer2": await sign_in(http, "a_c2@example.com", roles=["customer"], n=3, join="a@example.com"),
        "nobody": await sign_in(http, "a_nobody@example.com", roles=[], n=4, join="a@example.com"),
        "b_admin": await sign_in(http, "b@example.com", roles=["admin"], n=5),
    }


async def upload(http: AsyncClient, who: dict[str, str], content: str = DOC, kind: str = "invoice", **extra: object) -> Response:
    return await http.post("/ai/documents", json={"kind": kind, "title": "Doc", "content": content, **extra}, headers=who)


async def created(http: AsyncClient, who: dict[str, str], content: str = DOC, kind: str = "invoice") -> dict:
    r = await upload(http, who, content, kind)
    assert r.status_code == 201, r.text
    return r.json()


def field(doc: dict, name: str) -> dict:
    return next(f for f in doc["fields"] if f["name"] == name)


def error_code(r: Response) -> str:
    body = r.json()
    assert set(body) == {"code", "message", "details"} and isinstance(body["details"], list), body
    return body["code"]


async def rows(sql: str, **params: object) -> list[sa.Row]:
    async with session_factory() as session:
        return list((await session.execute(sa.text(sql), params)).all())


def lie(**field_answer: object) -> str:
    """A document whose text makes the fake provider answer exactly this (a lying or sloppy model)."""
    return DOC + "[[fake:json=" + json.dumps({"fields": {"total": field_answer}}, separators=(",", ":")) + "]]"


# --- extraction ----------------------------------------------------------------------------------------------


async def test_extraction_anchors_point_into_the_text_and_the_call_is_in_the_ledger(http, people) -> None:  # noqa: ANN001
    doc = await created(http, people["agent"])
    assert doc["status"] == "extracted" and doc["kind"] == "invoice" and doc["reviewed_by"] is None
    assert [f["name"] for f in doc["fields"]] == ["vendor", "total", "due_date"]
    values = {"vendor": "Acme Corp", "total": "1250.00", "due_date": "2026-12-01"}
    for name, value in values.items():
        f = field(doc, name)
        a = f["anchor"]
        assert f["value"] == value and f["confidence_bp"] == 9500 and not f["review_required"] and not f["corrected"]
        assert a["quote"] == value == DOC[a["start"] : a["end"]] and a["page"] == 1
        assert a["start"] == DOC.index(value) and a["end"] == a["start"] + len(value)
    call = (await rows("SELECT status, stage, cost_micro_usd, id, prompt_text, output_text FROM ai_calls"))[0]
    assert call.prompt_text is None and call.output_text is None  # document text lives in ai_documents only (SENTINEL H1)
    listed_calls = (await http.get("/ai/calls", headers=people["admin"])).json()["items"]
    assert listed_calls and all("prompt_text" not in c and "output_text" not in c for c in listed_calls)
    assert call.status == "ok" and call.stage == "extract" and call.cost_micro_usd > 0 and str(call.id) == doc["call_id"]
    u = (await http.get("/ai/usage", headers=people["admin"])).json()
    assert u["spent_micro_usd"] == call.cost_micro_usd and u["calls_ok"] == 1
    again = (await http.get(f"/ai/documents/{doc['id']}", headers=people["agent"])).json()
    assert again == doc and doc["content"] == DOC
    listed = (await http.get("/ai/documents", headers=people["agent"])).json()["items"][0]
    assert listed["content"] is None and listed["id"] == doc["id"]  # the list omits the text


async def test_anchors_use_whole_text_offsets_and_pages_split_on_form_feed(http, people) -> None:  # noqa: ANN001
    text = "page one\nvendor: Acme Corp\n\fpage two\ntotal: 99.50\n\fpage three\ndue date: tomorrow\n"
    doc = await created(http, people["agent"], text)
    for name, page in (("vendor", 1), ("total", 2), ("due_date", 3)):
        a = field(doc, name)["anchor"]
        assert a["page"] == page and text[a["start"] : a["end"]] == a["quote"] == field(doc, name)["value"]


async def test_a_long_text_is_split_into_segments_and_offsets_stay_absolute(http, people) -> None:  # noqa: ANN001
    text = ("filler line\n" * 3000) + "vendor: Late Vendor\ntotal: 7.00\n"
    assert len(text) > 19_000
    doc = await created(http, people["agent"], text)
    for name in ("vendor", "total"):
        a = field(doc, name)["anchor"]
        assert text[a["start"] : a["end"]] == a["quote"] == field(doc, name)["value"] and a["start"] > 19_000


async def test_low_confidence_and_the_threshold_edge_go_to_review(http, people) -> None:  # noqa: ANN001
    edge = await created(http, people["agent"], "vendor: A [[conf=8000]]\ntotal: 5 [[conf=7999]]\n")
    assert field(edge, "vendor")["confidence_bp"] == 8000 and not field(edge, "vendor")["review_required"]
    assert field(edge, "total")["confidence_bp"] == 7999 and field(edge, "total")["review_required"]
    assert edge["status"] == "needs_review"
    unsure = await created(http, people["agent"], "vendor: A\ntotal: 5?\n")
    assert field(unsure, "total")["confidence_bp"] == 4000 and unsure["status"] == "needs_review"
    sure = await created(http, people["agent"], "vendor: A [[conf=8000]]\ntotal: 5 [[conf=10000]]\n")
    assert sure["status"] == "extracted"  # the optional due_date is missing but that alone does not need review
    assert field(sure, "due_date")["value"] is None and field(sure, "due_date")["review_required"]


async def test_a_missing_required_field_needs_review_and_has_no_anchor(http, people) -> None:  # noqa: ANN001
    doc = await created(http, people["agent"], "vendor: Acme\n")
    total = field(doc, "total")
    assert doc["status"] == "needs_review"
    assert total["value"] is None and total["anchor"] is None and total["confidence_bp"] == 0 and total["review_required"]
    receipt = await created(http, people["agent"], "merchant: Shop\n", kind="receipt")
    assert receipt["status"] == "needs_review" and [f["name"] for f in receipt["fields"]] == ["merchant", "amount"]


@pytest.mark.parametrize(
    "answer",
    [
        {"value": "999", "confidence_bp": 9900, "start": 0, "end": 3, "quote": "zzz"},  # the quote is not at those offsets
        {"value": "999", "confidence_bp": 9900, "start": 5000, "end": 5003, "quote": "999"},  # beyond the text
        {"value": "999", "confidence_bp": 9900, "start": 10, "end": 10, "quote": ""},  # empty range
        {"value": "999", "confidence_bp": 9900, "start": 20, "end": 10, "quote": "x"},  # reversed
        {"value": "999", "confidence_bp": 9900, "start": -3, "end": 2, "quote": "IN"},  # negative
        {"value": "999", "confidence_bp": 9900, "start": "0", "end": "2", "quote": "IN"},  # not integers
        {"value": "999", "confidence_bp": 9900},  # no anchor at all
    ],
)
async def test_a_lying_model_anchor_is_never_accepted(http, people, answer) -> None:  # noqa: ANN001
    doc = await created(http, people["agent"], lie(**answer))
    total = field(doc, "total")
    assert total["value"] == "999" and total["anchor"] is None and total["confidence_bp"] == 0 and total["review_required"]
    assert doc["status"] == "needs_review"


@pytest.mark.parametrize("confidence", ["high", 1.5, -1, 10001, True, None])
async def test_a_bad_confidence_is_zero_even_with_a_good_anchor(http, people, confidence) -> None:  # noqa: ANN001
    text = DOC
    start = text.index("1250.00")
    doc = await created(http, people["agent"], lie(value="1250.00", confidence_bp=confidence, start=start, end=start + 7, quote="1250.00"))
    total = field(doc, "total")
    assert total["confidence_bp"] == 0 and total["review_required"] and doc["status"] == "needs_review"
    assert total["anchor"] is not None and total["anchor"]["quote"] == "1250.00"


async def test_the_model_cannot_invent_fields_outside_the_kind(http, people) -> None:  # noqa: ANN001
    text = DOC + '[[fake:json={"fields":{"secret":{"value":"x","confidence_bp":9999,"start":0,"end":1,"quote":"I"}}}]]'
    doc = await created(http, people["agent"], text)
    assert [f["name"] for f in doc["fields"]] == ["vendor", "total", "due_date"]
    assert all(f["value"] is None for f in doc["fields"]) and doc["status"] == "needs_review"


async def test_a_failing_provider_leaves_no_document_and_a_failed_ledger_row(http, people) -> None:  # noqa: ANN001
    r = await upload(http, people["agent"], DOC + "[[fake:fail]]")
    assert r.status_code == 502 and error_code(r) == "provider_error"
    assert (await rows("SELECT count(*) FROM ai_documents"))[0][0] == 0
    assert (await rows("SELECT status FROM ai_calls"))[0][0] == "error"


async def test_input_errors(http, people) -> None:  # noqa: ANN001
    agent = people["agent"]
    assert error_code(await upload(http, agent, kind="nope")) == "unknown_kind"
    assert (await upload(http, agent, kind="nope")).status_code == 422
    too_big = await upload(http, agent, "x" * 200_001)
    assert too_big.status_code == 422 and error_code(too_big) == "content_too_large"
    empty = await upload(http, agent, "")
    assert empty.status_code == 422 and error_code(empty) == "validation_error"
    r = await http.post("/ai/documents", json={"kind": "invoice", "title": "t", "content": "c", "x": 1}, headers=agent)
    assert r.status_code == 422
    bad = await http.get("/ai/documents", params={"status": "weird"}, headers=agent)
    assert bad.status_code == 422 and error_code(bad) == "validation_error"
    assert (await http.get("/ai/documents/00000000-0000-0000-0000-000000000000", headers=agent)).status_code == 404
    assert (await rows("SELECT count(*) FROM ai_calls"))[0][0] == 0  # nothing reached the gateway


# --- review --------------------------------------------------------------------------------------------------


async def test_correct_approve_flow_and_final_states(http, people) -> None:  # noqa: ANN001
    doc = await created(http, people["agent"], "vendor: Acme\n")
    admin, agent = people["admin"], people["agent"]
    base = f"/ai/documents/{doc['id']}"
    r = await http.post(f"{base}/approve", headers=admin)
    assert r.status_code == 422 and error_code(r) == "missing_required_fields" and r.json()["details"] == [{"name": "total"}]
    assert (await http.post(f"{base}/fields/total/correct", json={"value": "10.00"}, headers=agent)).status_code == 403
    assert (await http.post(f"{base}/approve", headers=agent)).status_code == 403
    r = await http.post(f"{base}/fields/nope/correct", json={"value": "1"}, headers=admin)
    assert r.status_code == 404 and error_code(r) == "unknown_field"
    r = await http.post(f"{base}/fields/total/correct", json={"value": "10.00"}, headers=admin)
    assert r.status_code == 200
    fixed = r.json()
    total = field(fixed, "total")
    assert total["value"] == "10.00" and total["corrected"] and total["confidence_bp"] == 10000 and total["original_value"] is None
    assert fixed["status"] == "needs_review"  # moves on only through approve
    vendor = field(fixed, "vendor")
    r = await http.post(f"{base}/fields/vendor/correct", json={"value": "Acme Ltd"}, headers=admin)
    vendor = field(r.json(), "vendor")
    assert vendor["original_value"] == "Acme" and vendor["anchor"] is None  # the old quote no longer describes the value
    r = await http.post(f"{base}/fields/vendor/correct", json={"value": "Acme GmbH"}, headers=admin)
    assert field(r.json(), "vendor")["original_value"] == "Acme"  # the extracted value is kept
    r = await http.post(f"{base}/approve", headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["reviewed_by"] is not None and r.json()["reviewed_at"]
    for call in (
        http.post(f"{base}/approve", headers=admin),
        http.post(f"{base}/reject", json={"reason": "late"}, headers=admin),
        http.post(f"{base}/fields/total/correct", json={"value": "1"}, headers=admin),
    ):
        r = await call
        assert r.status_code == 409 and error_code(r) == "document_closed"
    assert (await http.get(base, headers=admin)).json()["status"] == "approved"


async def test_reject_with_and_without_a_reason_and_approve_from_extracted(http, people) -> None:  # noqa: ANN001
    admin = people["admin"]
    d1 = await created(http, people["agent"], "vendor: A\ntotal: 1\n")
    r = await http.post(f"/ai/documents/{d1['id']}/reject", json={"reason": "duplicate"}, headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "rejected" and r.json()["reject_reason"] == "duplicate"
    d2 = await created(http, people["agent"], "vendor: A\ntotal: 1\n")
    r = await http.post(f"/ai/documents/{d2['id']}/reject", headers=admin)
    assert r.status_code == 200 and r.json()["reject_reason"] is None
    d3 = await created(http, people["agent"], "vendor: A\ntotal: 1\n")
    assert d3["status"] == "extracted"
    assert (await http.post(f"/ai/documents/{d3['id']}/approve", headers=admin)).json()["status"] == "approved"
    assert (await http.post(f"/ai/documents/{d3['id']}/reject", json={"reason": "x" * 501}, headers=admin)).status_code == 422


async def test_correcting_a_field_to_nothing_blocks_approval_of_a_required_field(http, people) -> None:  # noqa: ANN001
    doc = await created(http, people["agent"], "vendor: A\ntotal: 1\n")
    admin = people["admin"]
    r = await http.post(f"/ai/documents/{doc['id']}/fields/total/correct", json={"value": ""}, headers=admin)
    assert field(r.json(), "total")["value"] is None and field(r.json(), "total")["review_required"]
    r = await http.post(f"/ai/documents/{doc['id']}/approve", headers=admin)
    assert r.status_code == 422 and error_code(r) == "missing_required_fields"


async def test_eight_parallel_decisions_have_exactly_one_winner(http, people) -> None:  # noqa: ANN001
    admin = people["admin"]
    for mix in ("approve", "mixed"):
        doc = await created(http, people["agent"], "vendor: A\ntotal: 1 [[conf=100]]\n")  # needs_review, total present
        calls = []
        for i in range(8):
            if mix == "approve" or i % 2 == 0:
                calls.append(http.post(f"/ai/documents/{doc['id']}/approve", json={"acknowledge": ["total"]}, headers=admin))
            else:
                calls.append(http.post(f"/ai/documents/{doc['id']}/reject", json={"reason": f"r{i}"}, headers=admin))
        results = await asyncio.gather(*calls)
        codes = sorted(r.status_code for r in results)
        assert codes == [200] + [409] * 7, [r.text for r in results]
        winner = next(r for r in results if r.status_code == 200).json()
        assert all(error_code(r) == "document_closed" for r in results if r.status_code == 409)
        final = (await http.get(f"/ai/documents/{doc['id']}", headers=admin)).json()
        assert final["status"] == winner["status"] and final["status"] in ("approved", "rejected")
        assert final["reviewed_at"] == winner["reviewed_at"] and final["reject_reason"] == winner["reject_reason"]


async def test_the_review_queue_lists_only_needs_review_newest_first(http, people) -> None:  # noqa: ANN001
    agent, admin = people["agent"], people["admin"]
    ok = await created(http, agent, "vendor: A\ntotal: 1\n")
    bad1 = await created(http, agent, "vendor: A\n")
    bad2 = await created(http, agent, "total: 2?\n")
    page = (await http.get("/ai/documents", params={"status": "needs_review"}, headers=admin)).json()
    assert set(page) == {"items", "total", "limit", "offset"} and page["total"] == 2
    assert [d["id"] for d in page["items"]] == [bad2["id"], bad1["id"]]
    assert all(f["name"] for d in page["items"] for f in d["fields"])
    await http.post(f"/ai/documents/{bad1['id']}/reject", headers=admin)
    assert (await http.get("/ai/documents", params={"status": "needs_review"}, headers=admin)).json()["total"] == 1
    assert (await http.get("/ai/documents", params={"status": "rejected"}, headers=admin)).json()["total"] == 1
    allp = (await http.get("/ai/documents", params={"limit": 2, "offset": 1}, headers=admin)).json()
    assert allp["total"] == 3 and len(allp["items"]) == 2 and allp["limit"] == 2 and allp["offset"] == 1
    assert (await http.get("/ai/documents", params={"kind": "receipt"}, headers=admin)).json()["total"] == 0
    assert ok["status"] == "extracted"


# --- access --------------------------------------------------------------------------------------------------


async def test_roles_own_reads_and_tenant_isolation(http, people) -> None:  # noqa: ANN001
    admin, agent, customer, customer2 = people["admin"], people["agent"], people["customer"], people["customer2"]
    nobody, b_admin = people["nobody"], people["b_admin"]
    mine = await created(http, customer)
    theirs = await created(http, customer2)
    by_agent = await created(http, agent)
    # a role that is not allowed to upload or read at all
    assert (await upload(http, nobody)).status_code == 403
    assert error_code(await http.get("/ai/documents", headers=nobody)) == "forbidden"
    assert (await upload(http, admin)).status_code == 403  # the reviewer is not an uploader in this spec
    # an uploader who is not a reader sees only their own documents
    assert (await http.get(f"/ai/documents/{mine['id']}", headers=customer)).status_code == 200
    r = await http.get(f"/ai/documents/{theirs['id']}", headers=customer)
    assert r.status_code == 404 and error_code(r) == "not_found"
    assert [d["id"] for d in (await http.get("/ai/documents", headers=customer)).json()["items"]] == [mine["id"]]
    # readers and reviewers see the tenant
    assert (await http.get("/ai/documents", headers=agent)).json()["total"] == 3
    assert (await http.get("/ai/documents", headers=admin)).json()["total"] == 3
    assert (await http.get(f"/ai/documents/{by_agent['id']}", headers=admin)).status_code == 200
    # another tenant sees nothing and decides nothing
    other = await http.get("/ai/documents", headers=b_admin)
    assert other.status_code == 200 and other.json()["total"] == 0
    for call in (
        http.get(f"/ai/documents/{mine['id']}", headers=b_admin),
        http.post(f"/ai/documents/{mine['id']}/approve", headers=b_admin),
        http.post(f"/ai/documents/{mine['id']}/reject", headers=b_admin),
        http.post(f"/ai/documents/{mine['id']}/fields/total/correct", json={"value": "1"}, headers=b_admin),
    ):
        r = await call
        assert r.status_code == 404 and error_code(r) == "not_found"
    assert (await http.get(f"/ai/documents/{mine['id']}", headers=admin)).json()["status"] == mine["status"]
    # no token
    assert (await http.get("/ai/documents")).status_code == 401
    assert (await http.post("/ai/documents", json={"kind": "invoice", "title": "t", "content": "c"})).status_code == 401


# --- idempotency ---------------------------------------------------------------------------------------------


async def test_the_same_key_and_body_is_one_document_and_one_ledger_call(http, people) -> None:  # noqa: ANN001
    agent = people["agent"]
    first = await upload(http, agent, idempotency_key="k-1")
    second = await upload(http, agent, idempotency_key="k-1")
    assert first.status_code == 201 and second.status_code == 200 and second.headers["Idempotent-Replayed"] == "true"
    assert first.json() == second.json()
    conflict = await upload(http, agent, DOC + "more", idempotency_key="k-1")
    assert conflict.status_code == 409 and error_code(conflict) == "idempotency_conflict"
    assert (await rows("SELECT count(*) FROM ai_documents"))[0][0] == 1
    assert (await rows("SELECT count(*) FROM ai_calls"))[0][0] == 1
    # another caller may use the same key
    assert (await upload(http, people["customer"], idempotency_key="k-1")).status_code == 201


async def test_parallel_requests_with_one_key_make_one_document(http, people) -> None:  # noqa: ANN001
    results = await asyncio.gather(*[upload(http, people["agent"], idempotency_key="race") for _ in range(6)])
    assert sorted(r.status_code for r in results) == [200] * 5 + [201], [r.text for r in results]
    assert len({r.json()["id"] for r in results}) == 1
    assert (await rows("SELECT count(*) FROM ai_documents"))[0][0] == 1
    assert (await rows("SELECT count(*) FROM ai_calls"))[0][0] == 1


# --- SENTINEL fixes ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1000000", "12", "100.00 USD extra"])
async def test_a_value_the_quote_does_not_support_is_treated_as_an_anchor_failure(http, people, value) -> None:  # noqa: ANN001
    text = "total: 100.00\n"
    start = text.index("100.00")
    doc = await created(http, people["agent"], text + "[[fake:json=" + json.dumps({"fields": {"total": {"value": value, "confidence_bp": 10000, "start": start, "end": start + 6, "quote": "100.00"}}}, separators=(",", ":")) + "]]")
    total = field(doc, "total")
    assert total["confidence_bp"] == 0 and total["anchor"] is None and total["review_required"] and doc["status"] == "needs_review"
    # a formatted value of the same number is supported
    ok = await created(http, people["agent"], "total: $1,250.00\n[[fake:json=" + json.dumps({"fields": {"total": {"value": "1250.00", "confidence_bp": 9000, "start": 8, "end": 16, "quote": "1,250.00"}}}, separators=(",", ":")) + "]]")
    assert field(ok, "total")["anchor"] is not None and field(ok, "total")["confidence_bp"] == 9000


async def test_text_cannot_steer_the_provider_unless_the_test_switch_is_on(http, people, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(ai_config, "FAKE_DIRECTIVES", False)
    doc = await created(http, people["agent"], "vendor: A\ntotal: 5 [[conf=10000]] [[fake:fail]]\n[[fake:json={\"fields\":{}}]]")
    total = field(doc, "total")
    assert total["value"] == "5 [[conf=10000]] [[fake:fail]]" and total["confidence_bp"] == 9500  # the text is only text


async def test_approve_needs_flagged_fields_corrected_or_acknowledged(http, people) -> None:  # noqa: ANN001
    admin = people["admin"]
    doc = await created(http, people["agent"], "vendor: A [[conf=100]]\ntotal: 5?\n")
    base = f"/ai/documents/{doc['id']}"
    r = await http.post(f"{base}/approve", headers=admin)
    assert r.status_code == 409 and error_code(r) == "review_pending" and r.json()["details"] == [{"name": "total"}, {"name": "vendor"}]
    r = await http.post(f"{base}/approve", json={"acknowledge": ["total"]}, headers=admin)
    assert error_code(r) == "review_pending" and r.json()["details"] == [{"name": "vendor"}]
    r = await http.post(f"{base}/approve", json={"acknowledge": ["nope"]}, headers=admin)
    assert r.status_code == 404 and error_code(r) == "unknown_field"
    assert (await http.post(f"{base}/approve", json={"acknowledge": [], "x": 1}, headers=admin)).status_code == 422
    await http.post(f"{base}/fields/vendor/correct", json={"value": "Acme"}, headers=admin)  # a correction resolves the flag
    r = await http.post(f"{base}/approve", json={"acknowledge": ["total", "due_date"]}, headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "approved"


async def test_the_uploader_cannot_review_their_own_document(http, people) -> None:  # noqa: ANN001
    mine = await created(http, people["agent"], "vendor: A\ntotal: 1\n")
    async with session_factory() as session:
        await session.execute(sa.text("UPDATE auth_users SET roles = CAST('[\"agent\", \"admin\"]' AS jsonb) WHERE email = 'a_agent@example.com'"))
        await session.commit()
    agent = people["agent"]
    base = f"/ai/documents/{mine['id']}"
    for call in (http.post(f"{base}/approve", headers=agent), http.post(f"{base}/reject", headers=agent), http.post(f"{base}/fields/total/correct", json={"value": "2"}, headers=agent)):
        r = await call
        assert r.status_code == 403 and error_code(r) == "self_review_forbidden"
    assert (await http.get(base, headers=agent)).json()["status"] == "extracted"
    assert (await http.post(f"{base}/approve", headers=people["admin"])).status_code == 200  # someone else may


async def test_the_body_is_bounded_before_it_is_parsed_into_the_gateway(http, people) -> None:  # noqa: ANN001
    r = await http.post("/ai/documents", json={"kind": "invoice", "title": "t", "content": "x" * 2_000_001}, headers=people["agent"])
    assert r.status_code == 422 and error_code(r) == "validation_error"
    r = await upload(http, people["agent"], "x" * 380_001)
    assert r.status_code == 422 and error_code(r) == "content_too_large"
