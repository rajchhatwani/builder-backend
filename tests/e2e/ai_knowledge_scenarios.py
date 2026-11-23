"""Scenario tests for the AI pack, knowledge block (D35) in the generated `ai_documents_knowledge` project (copied into the
project's tests/ by tests/e2e/test_ai_knowledge_stack.py, run against a real Postgres). FAKE provider only.

Spec: knowledge stage answer (fake-small, fallback fake-embed), manage admin, read any signed-in user, chunk_chars 200;
roles admin / agent / customer; multi-tenant.
RAG PERMISSION TEST: a caller whose role is not in a source's allowed_roles never sees that source in search hits, ask
citations, ask answer text or the prompt sent to the model, even when the question matches it exactly; owner-only sources
are the creator's alone; the filter runs before ranking and LIMIT (a weak permitted hit still comes back with limit 1 while
strong hidden ones exist); another tenant sees nothing; a role change takes effect on the next request; ask costs go through
the gateway ledger (ai_calls, usage endpoint); with no permitted chunk the model is not called."""

import json

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient, Response

from app.ai import config as ai_config
from app.ai import providers
from app.db import session_factory
from app.main import app
from tests._auth_support import outbox, sign_in  # noqa: F401

PUBLIC = "Refund policy: a refund is paid within 14 days after the claim is approved."
HIDDEN = "Executive refund escalation password is ZEBRA-7731 and only the admin team may know it."
PRIVATE = "Agent private note: the refund override code is QUARTZ-4410, do not share it."
HIDDEN_SECRETS = ("ZEBRA-7731", "Executive refund escalation")
PRIVATE_SECRETS = ("QUARTZ-4410", "override code")
HIDDEN_QUERY = "executive escalation password ZEBRA-7731 admin team"  # shares no word with the public source


@pytest.fixture(autouse=True)
def _fake_directives(monkeypatch) -> None:  # noqa: ANN001
    """Generated code ignores [[fake:...]] markers by default (text is untrusted); the failure scenario switches them on."""
    monkeypatch.setattr(ai_config, "FAKE_DIRECTIVES", False)


@pytest.fixture
def sent(monkeypatch) -> list[list[str]]:  # noqa: ANN001
    """Every message list the gateway hands to the provider (what the model is really sent)."""
    seen: list[list[str]] = []
    real = providers.complete

    async def spy(kind, model, contents, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        seen.append(list(contents))
        return await real(kind, model, contents, *args, **kwargs)

    monkeypatch.setattr(providers, "complete", spy)
    return seen


@pytest.fixture(autouse=True)
def _call_roles(monkeypatch) -> None:  # noqa: ANN001
    """The spec lets only admin call the gateway; uploading / asking now needs a call role, so these scenarios grant the uploader roles one."""
    monkeypatch.setattr(ai_config, "CALL_ROLES", ("admin", "agent", "customer"))


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
        "nobody": await sign_in(http, "a_nobody@example.com", roles=[], n=3, join="a@example.com"),
        "b_admin": await sign_in(http, "b@example.com", roles=["admin"], n=4),
    }


async def add_source(http: AsyncClient, who: dict[str, str], text: str, title: str = "Doc", **vis: object) -> dict:
    r = await http.post("/ai/knowledge/sources", json={"title": title, "text": text, **vis}, headers=who)
    assert r.status_code == 201, r.text
    return r.json()


async def search(http: AsyncClient, who: dict[str, str], query: str, **extra: object) -> Response:
    return await http.post("/ai/knowledge/search", json={"query": query, **extra}, headers=who)


async def ask(http: AsyncClient, who: dict[str, str], question: str, **extra: object) -> Response:
    return await http.post("/ai/knowledge/ask", json={"question": question, **extra}, headers=who)


def error_code(r: Response) -> str:
    body = r.json()
    assert set(body) == {"code", "message", "details"} and isinstance(body["details"], list), body
    return body["code"]


async def rows(sql: str, **params: object) -> list[sa.Row]:
    async with session_factory() as session:
        return list((await session.execute(sa.text(sql), params)).all())


async def set_roles(email: str, roles: list[str]) -> None:
    async with session_factory() as session:
        await session.execute(sa.text("UPDATE auth_users SET roles = CAST(:r AS jsonb) WHERE email = :e"), {"r": json.dumps(roles), "e": email})
        await session.commit()


def leaks(payload: object, secrets: tuple[str, ...] = HIDDEN_SECRETS) -> list[str]:
    text = str(payload)
    return [s for s in secrets if s in text]


@pytest.fixture
async def library(http, people) -> dict[str, dict]:  # noqa: ANN001
    return {
        "public": await add_source(http, people["admin"], PUBLIC, "Refund policy", allowed_roles=["admin", "agent", "customer"]),
        "hidden": await add_source(http, people["admin"], HIDDEN, "Escalation", allowed_roles=["admin"]),
        "private": await add_source_as_agent(http, people),
    }


async def add_source_as_agent(http: AsyncClient, people: dict[str, dict[str, str]]) -> dict:
    # the agent is not a manager: an owner-only source of an agent is made by an admin user who is also an agent
    await set_roles("a_agent@example.com", ["agent", "admin"])
    source = await add_source(http, people["agent"], PRIVATE, "Agent note", owner_only=True)
    await set_roles("a_agent@example.com", ["agent"])
    return source


# --- the RAG permission test ---------------------------------------------------------------------------------


async def test_a_hidden_source_never_shows_in_search_even_for_an_exact_query(http, people, library) -> None:  # noqa: ANN001
    for who in ("customer", "agent", "nobody"):
        r = await search(http, people[who], HIDDEN_QUERY)
        assert r.status_code == 200, r.text
        assert library["hidden"]["id"] not in str(r.json()) and not leaks(r.json()), (who, r.json())
    admin_hits = (await search(http, people["admin"], HIDDEN_QUERY)).json()["hits"]
    assert admin_hits and admin_hits[0]["source_id"] == library["hidden"]["id"] and "ZEBRA-7731" in admin_hits[0]["text"]
    only = await search(http, people["customer"], "ZEBRA-7731 escalation password")
    assert only.json() == {"hits": []}


async def test_ask_never_cites_or_sends_or_answers_with_a_hidden_source(http, people, library, sent) -> None:  # noqa: ANN001
    before = (await rows("SELECT count(*) FROM ai_calls"))[0][0]
    r = await ask(http, people["customer"], HIDDEN_QUERY)  # matches only the hidden source
    assert r.status_code == 200, r.text
    assert r.json() == {"answer": "", "grounded": False, "citations": [], "call_id": None}
    assert (await rows("SELECT count(*) FROM ai_calls"))[0][0] == before  # no permitted chunk: the model is not called
    # a question that matches the hidden AND the public source: the answer and every citation come from the public one
    q = "refund escalation password and the refund paid within days"
    for who in ("customer", "agent"):
        body = (await ask(http, people[who], q)).json()
        assert body["grounded"] and body["call_id"] and not leaks(body), (who, body)
        cited = {c["source_id"] for c in body["citations"]}
        assert library["public"]["id"] in cited and library["hidden"]["id"] not in cited
        assert cited <= {library["public"]["id"], library["private"]["id"] if who == "agent" else library["public"]["id"]}
    prompts = " ".join(" ".join(m) for m in sent)
    assert "Refund policy" in prompts and not leaks(prompts)  # what the model was sent
    assert (await rows("SELECT count(*) FROM ai_calls WHERE prompt_text IS NOT NULL OR output_text IS NOT NULL"))[0][0] == 0  # not kept (H1)
    calls = (await http.get("/ai/calls", headers=people["admin"])).json()["items"]
    assert calls and all("prompt_text" not in c and "output_text" not in c for c in calls)
    # the admin may see the hidden source and so it is cited
    body = (await ask(http, people["admin"], q)).json()
    assert library["hidden"]["id"] in {c["source_id"] for c in body["citations"]}
    assert "ZEBRA-7731" in " ".join(sent[-1])  # the admin may see it, so it may be sent


async def test_owner_only_sources_belong_to_their_creator_alone(http, people, library) -> None:  # noqa: ANN001
    query = "agent private note refund override code QUARTZ-4410"
    own = (await search(http, people["agent"], query)).json()["hits"]
    assert own and own[0]["source_id"] == library["private"]["id"]
    for who in ("admin", "customer", "nobody", "b_admin"):
        r = await search(http, people[who], query)
        assert library["private"]["id"] not in str(r.json()) and not leaks(r.json(), PRIVATE_SECRETS), who
        body = (await ask(http, people[who], query)).json()
        assert not leaks(body, PRIVATE_SECRETS) and library["private"]["id"] not in str(body), who
    own_ask = (await ask(http, people["agent"], query)).json()
    assert own_ask["grounded"] and library["private"]["id"] in {c["source_id"] for c in own_ask["citations"]}
    # lists and counts
    def ids(page: dict) -> set[str]:
        return {s["id"] for s in page["items"]}
    agent_list = (await http.get("/ai/knowledge/sources", headers=people["agent"])).json()
    assert ids(agent_list) == {library["public"]["id"], library["private"]["id"]} and agent_list["total"] == 2
    admin_list = (await http.get("/ai/knowledge/sources", headers=people["admin"])).json()
    assert ids(admin_list) == {library["public"]["id"], library["hidden"]["id"]} and admin_list["total"] == 2
    customer_list = (await http.get("/ai/knowledge/sources", headers=people["customer"])).json()
    assert ids(customer_list) == {library["public"]["id"]} and customer_list["total"] == 1
    assert (await http.get("/ai/knowledge/sources", headers=people["nobody"])).json() == {"items": [], "total": 0, "limit": 50, "offset": 0}
    # nobody else can even delete it: it does not exist for them
    for who in ("admin", "customer", "b_admin"):
        r = await http.delete(f"/ai/knowledge/sources/{library['private']['id']}", headers=people[who])
        assert r.status_code == 404 and error_code(r) == "not_found", who


async def test_the_filter_runs_before_ranking_and_the_limit(http, people) -> None:  # noqa: ANN001
    for i in range(6):
        await add_source(http, people["admin"], f"quasar nebula pulsar quasar nebula {i} cluster", f"Strong {i}", allowed_roles=["admin"])
    await add_source(http, people["admin"], "A weak mention of a pulsar in the public manual.", "Weak", allowed_roles=["customer"])
    q = "quasar nebula pulsar cluster"
    admin_hits = (await search(http, people["admin"], q, limit=3)).json()["hits"]
    assert len(admin_hits) == 3 and all(h["title"].startswith("Strong") for h in admin_hits)
    one = (await search(http, people["customer"], q, limit=1)).json()["hits"]
    assert len(one) == 1 and one[0]["title"] == "Weak"  # strong hidden chunks cannot crowd the permitted one out
    asked = (await ask(http, people["customer"], q, limit=1)).json()
    assert asked["grounded"] and [c["title"] for c in asked["citations"]] == ["Weak"]


async def test_tenants_are_isolated(http, people) -> None:  # noqa: ANN001
    mine = await add_source(http, people["admin"], "Shared word: moonbase telemetry handbook.", "A handbook", allowed_roles=["admin", "customer"])
    theirs = await add_source(http, people["b_admin"], "Shared word: moonbase telemetry runbook.", "B runbook", allowed_roles=["admin", "customer"])
    for who, expected, other in (("admin", mine, theirs), ("b_admin", theirs, mine)):
        hits = (await search(http, people[who], "moonbase telemetry")).json()["hits"]
        assert [h["source_id"] for h in hits] == [expected["id"]]
        listed = (await http.get("/ai/knowledge/sources", headers=people[who])).json()
        assert [s["id"] for s in listed["items"]] == [expected["id"]] and listed["total"] == 1
        r = await http.delete(f"/ai/knowledge/sources/{other['id']}", headers=people[who])
        assert r.status_code == 404
        body = (await ask(http, people[who], "moonbase telemetry")).json()
        assert {c["source_id"] for c in body["citations"]} == {expected["id"]}
    assert (await rows("SELECT count(*) FROM ai_knowledge_sources"))[0][0] == 2


async def test_a_role_change_takes_effect_at_once(http, people, library) -> None:  # noqa: ANN001
    customer = people["customer"]
    assert (await search(http, customer, HIDDEN_QUERY)).json()["hits"] == []
    await set_roles("a_c@example.com", ["customer", "admin"])
    now = (await search(http, customer, HIDDEN_QUERY)).json()["hits"]
    assert now and now[0]["source_id"] == library["hidden"]["id"]
    assert (await ask(http, customer, HIDDEN_QUERY)).json()["grounded"] is True
    await set_roles("a_c@example.com", ["customer"])
    assert (await search(http, customer, HIDDEN_QUERY)).json()["hits"] == []
    assert (await ask(http, customer, HIDDEN_QUERY)).json()["grounded"] is False
    # inherited roles count the same way: dropping every role hides even the public source
    await set_roles("a_c@example.com", [])
    assert (await search(http, customer, "refund policy paid within days")).json()["hits"] == []


async def test_deleting_a_source_removes_its_chunks_from_every_read(http, people, library) -> None:  # noqa: ANN001
    r = await http.delete(f"/ai/knowledge/sources/{library['hidden']['id']}", headers=people["admin"])
    assert r.status_code == 204
    assert (await search(http, people["admin"], HIDDEN_QUERY)).json()["hits"] == []
    assert (await rows("SELECT count(*) FROM ai_knowledge_chunks c JOIN ai_knowledge_sources s ON s.id = c.source_id WHERE s.id = :i", i=library["hidden"]["id"]))[0][0] == 0
    assert (await rows("SELECT count(*) FROM ai_knowledge_chunks WHERE text LIKE '%ZEBRA%'"))[0][0] == 0
    # a visible source of someone else cannot be deleted by a non-manager non-owner
    r = await http.delete(f"/ai/knowledge/sources/{library['public']['id']}", headers=people["customer"])
    assert r.status_code == 403 and error_code(r) == "forbidden"
    assert (await http.delete(f"/ai/knowledge/sources/{library['public']['id']}", headers=people["admin"])).status_code == 204


# --- cost through the gateway --------------------------------------------------------------------------------


async def test_ask_costs_go_through_the_gateway_ledger_and_the_usage_endpoint(http, people, library) -> None:  # noqa: ANN001
    u0 = (await http.get("/ai/usage", headers=people["admin"])).json()
    body = (await ask(http, people["customer"], "how long until a refund is paid after approval")).json()
    assert body["grounded"] and body["answer"].startswith("fake:") and body["call_id"]
    call = (await rows("SELECT * FROM ai_calls WHERE id = :i", i=body["call_id"]))[0]
    assert call.stage == "answer" and call.status == "ok" and call.cost_micro_usd > 0 and call.output_text is None
    assert call.input_tokens > 0 and call.output_tokens > 0
    u1 = (await http.get("/ai/usage", headers=people["admin"])).json()
    assert u1["spent_micro_usd"] - u0["spent_micro_usd"] == call.cost_micro_usd and u1["calls_ok"] == u0["calls_ok"] + 1
    calls = (await http.get("/ai/calls", params={"stage": "answer"}, headers=people["admin"])).json()
    assert [c["id"] for c in calls["items"]] == [body["call_id"]]
    assert 0 < body["citations"][0]["score_bp"] <= 10000 and body["citations"][0]["title"] == "Refund policy"
    # an unmatched question costs nothing
    none = (await ask(http, people["customer"], "completely unrelated gardening question zzz")).json()
    assert none["grounded"] is False and none["call_id"] is None
    assert (await http.get("/ai/usage", headers=people["admin"])).json()["spent_micro_usd"] == u1["spent_micro_usd"]


async def test_a_chunk_cannot_poison_ask_but_a_real_provider_failure_passes_through(http, people, monkeypatch) -> None:  # noqa: ANN001
    await add_source(http, people["admin"], "Marker text for failure [[fake:fail]] tolerance", "Fail", allowed_roles=["customer"])
    r = await ask(http, people["customer"], "marker text failure tolerance")  # directives are off: the chunk is only text
    assert r.status_code == 200 and r.json()["grounded"] is True
    monkeypatch.setattr(ai_config, "FAKE_DIRECTIVES", True)  # the test switch on: now the marker makes the provider fail
    r = await ask(http, people["customer"], "marker text failure tolerance")
    assert r.status_code == 502 and error_code(r) == "provider_error"
    assert (await rows("SELECT status FROM ai_calls ORDER BY created_at DESC LIMIT 1"))[0][0] == "error"


# --- ranking, chunking, validation ---------------------------------------------------------------------------


async def test_ranking_is_deterministic_integer_basis_points_and_best_first(http, people) -> None:  # noqa: ANN001
    await add_source(http, people["admin"], "Alpha beta gamma delta. " * 3, "Full", allowed_roles=["customer"])
    await add_source(http, people["admin"], "Alpha only appears here, nothing else of note.", "Partial", allowed_roles=["customer"])
    a = (await search(http, people["customer"], "alpha beta gamma delta")).json()["hits"]
    b = (await search(http, people["customer"], "alpha beta gamma delta")).json()["hits"]
    assert a == b and [h["title"] for h in a] == ["Full", "Partial"]
    assert all(isinstance(h["score_bp"], int) and 0 <= h["score_bp"] <= 10000 for h in a)
    assert a[0]["score_bp"] > a[1]["score_bp"]
    assert (await search(http, people["customer"], "the of is")).json() == {"hits": []}  # only stop words


async def test_long_text_is_chunked_to_chunk_chars(http, people) -> None:  # noqa: ANN001
    text = " ".join(f"Sentence number {i} talks about the topic harbor." for i in range(40))
    source = await add_source(http, people["admin"], text, "Long", allowed_roles=["customer"])
    assert source["chunk_count"] > 5 and source["owner_only"] is False and source["allowed_roles"] == ["customer"]
    hits = (await search(http, people["customer"], "harbor topic", limit=20)).json()["hits"]
    assert len(hits) == source["chunk_count"] and all(len(h["text"]) <= 200 for h in hits)
    assert sorted(h["position"] for h in hits) == list(range(source["chunk_count"]))
    assert (await search(http, people["customer"], "harbor topic", limit=2)).json()["hits"].__len__() == 2


async def test_source_validation_and_roles(http, people) -> None:  # noqa: ANN001
    admin = people["admin"]

    async def post(**body: object) -> Response:
        return await http.post("/ai/knowledge/sources", json={"title": "t", "text": "some text here", **body}, headers=admin)

    assert error_code(await post()) == "visibility_required"
    assert error_code(await post(allowed_roles=[])) == "visibility_required"
    assert error_code(await post(owner_only=False)) == "visibility_required"
    assert error_code(await post(allowed_roles=["admin"], owner_only=True)) == "visibility_conflict"
    r = await post(allowed_roles=["wizard"])
    assert r.status_code == 422 and error_code(r) == "unknown_role"
    assert (await post(allowed_roles=["admin"], owner_only=False)).status_code == 201
    mine = await post(owner_only=True)
    assert mine.status_code == 201 and mine.json()["allowed_roles"] == [] and mine.json()["owner_only"] is True
    r = await http.post("/ai/knowledge/sources", json={"title": "t", "text": "x" * 500_001, "owner_only": True}, headers=admin)
    assert r.status_code == 422 and error_code(r) == "content_too_large"
    r = await http.post("/ai/knowledge/sources", json={"title": "t", "text": "x" * 5_000_001, "owner_only": True}, headers=admin)
    assert r.status_code == 422 and error_code(r) == "validation_error"  # refused by the schema before any work
    assert (await http.post("/ai/knowledge/sources", json={"title": "", "text": "x", "owner_only": True}, headers=admin)).status_code == 422
    assert (await http.post("/ai/knowledge/sources", json={"title": "t", "text": "  ", "owner_only": True}, headers=admin)).status_code == 422
    # only a manager creates sources
    for who in ("customer", "agent", "nobody"):
        r = await http.post("/ai/knowledge/sources", json={"title": "t", "text": "x y", "owner_only": True}, headers=people[who])
        assert r.status_code == 403 and error_code(r) == "forbidden", who
    assert (await http.post("/ai/knowledge/sources", json={"title": "t", "text": "x", "owner_only": True})).status_code == 401
    for path, body in (("/ai/knowledge/search", {"query": ""}), ("/ai/knowledge/search", {"query": "a", "limit": 21}), ("/ai/knowledge/ask", {"question": "a", "limit": 11})):
        r = await http.post(path, json=body, headers=admin)
        assert r.status_code == 422 and error_code(r) == "validation_error"


# --- L5 / L4: ask needs a gateway call role, the source cap is a tenant total without a count ---------------------


async def test_ask_needs_a_gateway_call_role_before_any_retrieval(http, people, library, monkeypatch) -> None:  # noqa: ANN001
    from app.ai import knowledge_service

    monkeypatch.setattr(ai_config, "CALL_ROLES", ("admin",))
    monkeypatch.setattr(ai_config, "MANAGE_ROLES", ("admin",))
    real = knowledge_service.search
    searched: list[str] = []

    async def spy(session, user, query, limit):  # noqa: ANN001, ANN202
        searched.append(query)
        return await real(session, user, query, limit)

    monkeypatch.setattr(knowledge_service, "search", spy)
    r = await ask(http, people["customer"], "refund policy")  # may read the library, holds no call role
    assert r.status_code == 403 and error_code(r) == "forbidden", r.text
    assert searched == [] and (await rows("SELECT count(*) FROM ai_calls"))[0][0] == 0
    ok = await ask(http, people["admin"], "refund policy")
    assert ok.status_code == 200 and ok.json()["grounded"] is True and searched == ["refund policy"]
    assert (await rows("SELECT count(*) FROM ai_calls"))[0][0] == 1


async def test_the_source_cap_counts_every_tenant_source_and_the_message_carries_no_count(http, people, monkeypatch) -> None:  # noqa: ANN001
    from app.ai import knowledge_config

    await add_source_as_agent(http, people)  # an owner-only source the admin cannot see
    monkeypatch.setattr(knowledge_config, "MAX_SOURCES", 1)
    r = await http.post("/ai/knowledge/sources", json={"title": "t", "text": "another source", "owner_only": True}, headers=people["admin"])
    assert r.status_code == 422 and error_code(r) == "limit_reached", r.text
    assert not any(ch.isdigit() for ch in r.json()["message"]), r.json()["message"]
    assert (await rows("SELECT count(*) FROM ai_knowledge_sources"))[0][0] == 1
