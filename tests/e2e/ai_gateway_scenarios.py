"""Scenario tests for the AI pack, gateway block (D33) in the generated `ai_gateway_support` project (copied into the
project's tests/ by tests/e2e/test_ai_gateway_stack.py, run against a real Postgres). FAKE provider only.

Spec: stages classify (fake-small, 100 output tokens) and summarize (fake-small, 120, fallback fake-embed); budget 200
micro-USD per day, per-call cap 100; roles: call admin/agent, read admin/agent, manage admin; multi-tenant.
Proves: 8 parallel calls with a budget for exactly 3 give 3 x 200 and 5 x 429 and spent never above the budget; the
per-call cap; the ledger sums to the usage endpoint and the cost maths is exact; zero retention stores no text; a
provider error releases the reservation (also with a fallback model); idempotent parallel retries are one ledger row;
role refusals; tenant isolation; stale reservations are released; no 500 anywhere."""

import asyncio
import math
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient, Response

from app.ai import config as ai_config
from app.db import session_factory
from app.main import app
from tests._auth_support import outbox, sign_in  # noqa: F401

LIMIT = 200  # budget of the period in micro-USD (spec)
FILL = "ping [[fake:out=100]] [[fake:delay=400]]"  # exactly 100 output tokens, 400 ms: cost == worst case
FILL_TOKENS = math.ceil(len(FILL) / 4)
FILL_COST = math.ceil(FILL_TOKENS * 150_000 / 1_000_000) + math.ceil(100 * 600_000 / 1_000_000)  # in + out, micro-USD


@pytest.fixture(autouse=True)
def _fake_directives(monkeypatch) -> None:  # noqa: ANN001
    """Generated code ignores [[fake:...]] markers by default (message text is untrusted); these scenarios drive the fake with them."""
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
        "nobody": await sign_in(http, "a_nobody@example.com", roles=[], n=3, join="a@example.com"),
        "b_admin": await sign_in(http, "b@example.com", roles=["admin"], n=4),
    }


def msgs(text: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": text}]


async def complete(http: AsyncClient, who: dict[str, str], text: str = "hello", stage: str = "classify", **extra: object) -> Response:
    return await http.post("/ai/complete", json={"stage": stage, "messages": msgs(text), **extra}, headers=who)


async def usage(http: AsyncClient, who: dict[str, str]) -> dict:
    r = await http.get("/ai/usage", headers=who)
    assert r.status_code == 200, r.text
    return r.json()


async def rows(sql: str, **params: object) -> list[sa.Row]:
    async with session_factory() as session:
        return list((await session.execute(sa.text(sql), params)).all())


async def execute(sql: str, **params: object) -> None:
    async with session_factory() as session:
        await session.execute(sa.text(sql), params)
        await session.commit()


def error_shape(r: Response) -> str:
    body = r.json()
    assert set(body) == {"code", "message", "details"} and isinstance(body["details"], list), body
    return body["code"]


# --- the budget ----------------------------------------------------------------------------------------------


async def test_the_fill_call_costs_what_the_worst_case_reserves() -> None:
    assert FILL_COST * 3 <= LIMIT < FILL_COST * 4  # the arithmetic of the scenarios below
    assert ai_config.BUDGET_LIMIT_MICRO_USD == LIMIT and ai_config.ZERO_RETENTION is False


async def test_eight_parallel_calls_with_a_budget_for_three(http, people) -> None:  # noqa: ANN001
    agent = people["agent"]
    results = await asyncio.gather(*[complete(http, agent, FILL, max_output_tokens=100) for _ in range(8)])
    codes = sorted(r.status_code for r in results)
    assert codes == [200] * 3 + [429] * 5, [r.text for r in results if r.status_code not in (200, 429)]
    for r in results:
        if r.status_code == 429:
            assert error_shape(r) == "budget_exceeded"
            detail = r.json()["details"][0]
            assert detail["limit_micro_usd"] == LIMIT and detail["requested_micro_usd"] == FILL_COST
        else:
            assert r.json()["cost_micro_usd"] == FILL_COST and r.json()["status"] == "ok"
    u = await usage(http, agent)
    assert u["spent_micro_usd"] == 3 * FILL_COST <= LIMIT and u["reserved_micro_usd"] == 0
    assert u["remaining_micro_usd"] == LIMIT - 3 * FILL_COST and u["calls_ok"] == 3 and u["calls_error"] == 0
    assert (await rows("SELECT count(*) FROM ai_calls"))[0][0] == 3  # a refused call leaves no ledger row
    # all-or-nothing: the leftover cannot pay for another worst case
    assert error_shape(await complete(http, agent, FILL, max_output_tokens=100)) == "budget_exceeded"


async def test_spent_plus_reserved_never_exceeds_the_budget_while_calls_are_in_flight(http, people) -> None:  # noqa: ANN001
    agent = people["agent"]
    admin = people["admin"]
    tasks = [asyncio.create_task(complete(http, agent, FILL, max_output_tokens=100)) for _ in range(6)]
    seen = []
    for _ in range(12):
        u = await usage(http, admin)
        seen.append(u["spent_micro_usd"] + u["reserved_micro_usd"])
        await asyncio.sleep(0.05)
    await asyncio.gather(*tasks)
    assert max(seen) <= LIMIT and max(seen) >= FILL_COST  # reservations were visible while the calls ran


async def test_per_call_cap_and_stage_limits(http, people) -> None:  # noqa: ANN001
    agent = people["agent"]
    big = "x" * 2000  # 500 input tokens -> 75 micro-USD in, 60 out: worst case 135 > cap 100
    r = await complete(http, agent, big)
    assert r.status_code == 422 and error_shape(r) == "per_call_cap_exceeded"
    assert r.json()["details"][0] == {"worst_case_micro_usd": 135, "per_call_cap_micro_usd": 100}
    assert (await rows("SELECT count(*) FROM ai_calls"))[0][0] == 0  # nothing reserved, no ledger row
    assert (await usage(http, agent))["reserved_micro_usd"] == 0
    assert error_shape(await complete(http, agent, "hi", max_output_tokens=101)) == "validation_error"
    assert (await complete(http, agent, "hi", max_output_tokens=10)).status_code == 200
    for bad in ({"messages": []}, {"messages": msgs("")}, {"max_output_tokens": 2.5}, {"stage": ""}, {"extra": 1}):
        r = await http.post("/ai/complete", json={"stage": "classify", "messages": msgs("hi"), **bad}, headers=agent)
        assert r.status_code == 422 and error_shape(r) == "validation_error", bad
    assert error_shape(await complete(http, agent, stage="nope")) == "unknown_stage"
    assert (await complete(http, agent, stage="nope")).status_code == 404


# --- the ledger ----------------------------------------------------------------------------------------------


async def test_ledger_rows_sum_to_usage_and_the_cost_maths_is_exact(http, people) -> None:  # noqa: ANN001
    agent, admin = people["agent"], people["admin"]
    first = await complete(http, agent, "hello")  # 5 chars -> 2 tokens in; "fake:" + 16 hex = 21 chars -> 6 tokens out
    body = first.json()
    assert first.status_code == 200 and (body["input_tokens"], body["output_tokens"]) == (2, 6)
    assert body["cost_micro_usd"] == 1 + 4 and body["output_text"].startswith("fake:") and body["output_json"] is None
    assert body["provider"] == "main" and body["model"] == "fake-small" and body["fallback_used"] is False
    again = await complete(http, agent, "hello")  # deterministic: same output
    assert again.json()["output_text"] == body["output_text"]
    for text in ("one", "two two", "three three three"):
        assert (await complete(http, admin, text, stage="summarize")).status_code == 200
    calls = (await http.get("/ai/calls", params={"limit": 3}, headers=admin)).json()
    assert set(calls) == {"items", "total", "limit", "offset"} and calls["total"] == 5 and len(calls["items"]) == 3
    everything = (await http.get("/ai/calls", params={"limit": 200}, headers=admin)).json()["items"]
    u = await usage(http, admin)
    assert sum(c["cost_micro_usd"] for c in everything) == u["spent_micro_usd"] > 0
    assert sum(c["input_tokens"] for c in everything) == u["input_tokens"]
    assert sum(c["output_tokens"] for c in everything) == u["output_tokens"]
    assert u["calls_ok"] == 5 and u["limit_micro_usd"] == LIMIT and u["period"] == "day" and u["region"] == "eu"
    assert u["remaining_micro_usd"] == LIMIT - u["spent_micro_usd"] - u["reserved_micro_usd"]
    assert all(c["status"] == "ok" and len(c["prompt_hash"]) == 64 for c in everything)
    assert all("prompt_text" not in c and "output_text" not in c for c in everything)  # the ledger API never returns text (SENTINEL H1)
    assert (await rows("SELECT count(*) FROM ai_calls WHERE prompt_text IS NOT NULL AND output_text IS NOT NULL"))[0][0] == 5
    assert [c["created_at"] for c in everything] == sorted((c["created_at"] for c in everything), reverse=True)
    only = (await http.get("/ai/calls", params={"stage": "summarize"}, headers=admin)).json()
    assert only["total"] == 3 and all(c["stage"] == "summarize" for c in only["items"])
    assert (await http.get("/ai/calls", params={"status": "error"}, headers=admin)).json()["total"] == 0
    # the database agrees (BIGINT micro-USD, no floats)
    assert (await rows("SELECT sum(cost_micro_usd) FROM ai_calls"))[0][0] == u["spent_micro_usd"]


async def test_structured_json_output(http, people) -> None:  # noqa: ANN001
    agent = people["agent"]
    r = await complete(http, agent, "extract", response_format="json")
    assert r.status_code == 200 and isinstance(r.json()["output_json"], dict) and "echo" in r.json()["output_json"]
    fixed = await complete(http, agent, 'extract [[fake:json={"total": 1250, "ok": true}]]', response_format="json", max_output_tokens=50)
    assert fixed.json()["output_json"] == {"total": 1250, "ok": True}
    bad = await complete(http, agent, "extract [[fake:json=not json]]", response_format="json")
    assert bad.status_code == 502 and error_shape(bad) == "invalid_output"
    failed = (await http.get("/ai/calls", params={"status": "error"}, headers=agent)).json()["items"]
    assert [c["error_code"] for c in failed] == ["invalid_output"] and failed[0]["cost_micro_usd"] > 0  # the tokens were spent
    u = await usage(http, agent)
    assert u["reserved_micro_usd"] == 0 and u["calls_error"] == 1 and u["calls_ok"] == 2


async def test_zero_retention_stores_no_text(http, people, monkeypatch) -> None:  # noqa: ANN001
    agent = people["agent"]
    stored = await complete(http, agent, "keep this secret-ish text")
    assert stored.status_code == 200
    monkeypatch.setattr(ai_config, "ZERO_RETENTION", True)
    r = await complete(http, agent, "never store this text", idempotency_key="zr-1")
    assert r.status_code == 200 and r.json()["output_text"].startswith("fake:")  # the live caller still gets the answer
    row = (await rows("SELECT prompt_text, output_text, prompt_hash, input_tokens, output_tokens, cost_micro_usd, status FROM ai_calls WHERE idempotency_key = 'zr-1'"))[0]
    assert row.prompt_text is None and row.output_text is None and len(row.prompt_hash) == 64
    assert row.input_tokens > 0 and row.output_tokens > 0 and row.cost_micro_usd > 0 and row.status == "ok"
    listed = (await http.get("/ai/calls", headers=agent)).json()["items"]
    secret = [c for c in listed if c["idempotency_key"] == "zr-1"][0]
    assert "prompt_text" not in secret and "output_text" not in secret
    assert (await rows("SELECT count(*) FROM ai_calls WHERE prompt_text IS NOT NULL"))[0][0] == 1  # the earlier call kept its text
    assert (await usage(http, agent))["zero_retention"] is True
    replay = await complete(http, agent, "never store this text", idempotency_key="zr-1")
    assert replay.json()["replayed"] is True and replay.json()["output_text"] is None
    assert (await rows("SELECT count(*) FROM ai_calls WHERE prompt_text LIKE '%never store%' OR output_text LIKE '%never store%'"))[0][0] == 0


# --- provider errors, fallback, stale reservations --------------------------------------------------------------


async def test_a_provider_error_releases_the_reservation(http, people) -> None:  # noqa: ANN001
    agent = people["agent"]
    for _ in range(5):  # five failures would exhaust the budget if their reservations leaked
        r = await complete(http, agent, "boom [[fake:fail]]")
        assert r.status_code == 502 and error_shape(r) == "provider_error"
    u = await usage(http, agent)
    assert (u["spent_micro_usd"], u["reserved_micro_usd"], u["calls_error"], u["calls_ok"]) == (0, 0, 5, 0)
    errors = (await http.get("/ai/calls", params={"status": "error"}, headers=agent)).json()
    assert errors["total"] == 5 and all(c["error_code"] == "provider_error" and c["cost_micro_usd"] == 0 and c["reserved_micro_usd"] == 0 for c in errors["items"])
    results = await asyncio.gather(*[complete(http, agent, FILL, max_output_tokens=100) for _ in range(3)])
    assert [r.status_code for r in results] == [200] * 3  # the full budget is still there
    assert (await usage(http, agent))["spent_micro_usd"] == 3 * FILL_COST


async def test_the_fallback_model_takes_over_when_the_primary_fails(http, people) -> None:  # noqa: ANN001
    agent = people["agent"]
    r = await complete(http, agent, "summarise [[fake:fail_primary]]", stage="summarize")
    body = r.json()
    assert r.status_code == 200 and body["fallback_used"] is True and body["model"] == "fake-embed"
    assert body["cost_micro_usd"] == math.ceil(body["input_tokens"] * 20_000 / 1_000_000)  # fake-embed: input only
    both = await complete(http, agent, "summarise [[fake:fail]]", stage="summarize")
    assert both.status_code == 502 and error_shape(both) == "provider_error"
    u = await usage(http, agent)
    assert u["reserved_micro_usd"] == 0 and u["calls_ok"] == 1 and u["calls_error"] == 1


async def test_a_stale_reservation_is_released(http, people) -> None:  # noqa: ANN001
    agent = people["agent"]
    assert (await complete(http, agent, "warm up")).status_code == 200
    tenant = (await rows("SELECT tenant_id FROM ai_budget_periods"))[0][0]
    old = datetime.now(UTC) - timedelta(seconds=ai_config.STALE_RESERVATION_SECONDS + 60)
    await execute("UPDATE ai_budget_periods SET reserved_micro_usd = 190")
    await execute(
        "INSERT INTO ai_calls (id, tenant_id, stage, provider, model, status, period_start, reserved_micro_usd, prompt_hash, created_at)"
        " SELECT gen_random_uuid(), :t, 'classify', 'main', 'fake-small', 'reserved', period_start, 190, repeat('a', 64), :old FROM ai_budget_periods",
        t=tenant,
        old=old,
    )
    assert (await usage(http, agent))["reserved_micro_usd"] == 190
    r = await complete(http, agent, "after the crash")  # the 190 would block it; the stale one is released first
    assert r.status_code == 200, r.text
    u = await usage(http, agent)
    assert u["reserved_micro_usd"] == 0 and u["calls_error"] == 1
    assert (await rows("SELECT error_code, reserved_micro_usd FROM ai_calls WHERE status = 'error'"))[0] == ("abandoned", 0)


# --- idempotency ---------------------------------------------------------------------------------------------


async def test_parallel_retries_with_one_key_make_one_call(http, people) -> None:  # noqa: ANN001
    agent = people["agent"]
    results = await asyncio.gather(*[complete(http, agent, FILL, max_output_tokens=100, idempotency_key="same-key") for _ in range(8)])
    assert [r.status_code for r in results] == [200] * 8, [r.text for r in results]
    assert len({r.json()["call_id"] for r in results}) == 1
    assert sorted(r.json()["replayed"] for r in results) == [False] + [True] * 7
    assert {r.json()["output_text"] for r in results}.__len__() == 1
    assert all(r.headers.get("Idempotent-Replayed") == "true" for r in results if r.json()["replayed"])
    assert (await rows("SELECT count(*) FROM ai_calls"))[0][0] == 1
    u = await usage(http, agent)
    assert u["spent_micro_usd"] == FILL_COST and u["reserved_micro_usd"] == 0
    other = await complete(http, agent, "something else", idempotency_key="same-key")
    assert other.status_code == 409 and error_shape(other) == "idempotency_conflict"
    # the key belongs to the caller: another caller with the same key makes a separate call
    assert (await complete(http, people["admin"], FILL, max_output_tokens=100, idempotency_key="same-key")).json()["replayed"] is False


async def test_an_errored_call_does_not_occupy_its_key(http, people) -> None:  # noqa: ANN001
    agent = people["agent"]
    assert (await complete(http, agent, "try [[fake:fail]]", idempotency_key="k-err")).status_code == 502
    ok = await complete(http, agent, "try again", idempotency_key="k-err")
    assert ok.status_code == 200 and ok.json()["replayed"] is False
    assert (await complete(http, agent, "try again", idempotency_key="k-err")).json()["replayed"] is True
    assert (await rows("SELECT count(*) FROM ai_calls WHERE idempotency_key = 'k-err'"))[0][0] == 2


# --- roles and tenants ---------------------------------------------------------------------------------------


async def test_roles_decide_who_may_call_and_read(http, people) -> None:  # noqa: ANN001
    admin, agent, customer, nobody = people["admin"], people["agent"], people["customer"], people["nobody"]
    for who in (customer, nobody):
        r = await complete(http, who)
        assert r.status_code == 403 and error_shape(r) == "forbidden"
        assert (await http.get("/ai/calls", headers=who)).status_code == 403
        assert (await http.get("/ai/usage", headers=who)).status_code == 403
    assert (await http.post("/ai/complete", json={"stage": "classify", "messages": msgs("hi")})).status_code == 401
    assert (await http.get("/ai/usage")).status_code == 401
    assert (await complete(http, agent)).status_code == 200 and (await complete(http, admin)).status_code == 200
    assert (await http.get("/ai/calls", headers=agent)).json()["total"] == 2  # readers see the whole tenant
    r = await http.get("/ai/calls", params={"limit": 0}, headers=admin)
    assert r.status_code == 422 and error_shape(r) == "validation_error"
    assert (await http.get("/ai/calls", params={"status": "weird"}, headers=admin)).status_code == 422
    assert (await rows("SELECT count(*) FROM ai_calls WHERE caller_id IS NULL"))[0][0] == 0


async def test_tenants_have_separate_ledgers_and_budgets(http, people) -> None:  # noqa: ANN001
    a, b = people["agent"], people["b_admin"]
    await asyncio.gather(*[complete(http, a, FILL, max_output_tokens=100) for _ in range(4)])
    assert (await usage(http, a))["spent_micro_usd"] == 3 * FILL_COST
    assert error_shape(await complete(http, a, FILL, max_output_tokens=100)) == "budget_exceeded"
    assert (await usage(http, b))["spent_micro_usd"] == 0 and (await http.get("/ai/calls", headers=b)).json()["total"] == 0
    results = await asyncio.gather(*[complete(http, b, FILL, max_output_tokens=100) for _ in range(3)])
    assert [r.status_code for r in results] == [200] * 3  # tenant A's exhausted budget does not touch tenant B
    assert (await http.get("/ai/calls", headers=a)).json()["total"] == 3
    assert (await rows("SELECT count(DISTINCT tenant_id) FROM ai_budget_periods"))[0][0] == 2


async def test_the_database_refuses_negative_amounts(people) -> None:  # noqa: ANN001
    with pytest.raises(sa.exc.IntegrityError):
        await execute(
            "INSERT INTO ai_budget_periods (id, period_start, spent_micro_usd, reserved_micro_usd, tenant_id)"
            " SELECT gen_random_uuid(), current_date, -5, 0, id FROM auth_tenants LIMIT 1"
        )


async def test_the_hash_is_salted_and_fake_directives_are_off_unless_enabled(http, people, monkeypatch) -> None:  # noqa: ANN001
    import hashlib
    import json

    agent = people["agent"]
    r = await complete(http, agent, "guessable")
    row = (await rows("SELECT prompt_hash FROM ai_calls"))[0]
    plain = hashlib.sha256(json.dumps(["classify", [["user", "guessable"]]], separators=(",", ":"), sort_keys=True).encode()).hexdigest()
    assert r.status_code == 200 and row.prompt_hash != plain and len(row.prompt_hash) == 64
    monkeypatch.setattr(ai_config, "FAKE_DIRECTIVES", False)
    ok = await complete(http, agent, "text [[fake:fail]] [[fake:delay=5000]]")
    assert ok.status_code == 200 and ok.json()["output_text"].startswith("fake:")  # untrusted text cannot steer the provider
    forced = await complete(http, agent, 'x [[fake:json={"a": 1}]]', response_format="json")
    assert forced.json()["output_json"] != {"a": 1}


async def test_a_hostile_body_is_bounded(http, people) -> None:  # noqa: ANN001
    import time

    agent = people["agent"]
    started = time.monotonic()
    body = "[[fake:a=" * 2200
    r = await http.post("/ai/complete", json={"stage": "summarize", "messages": [{"role": "user", "content": body}] * 40}, headers=agent)
    assert time.monotonic() - started < 5 and r.status_code in (200, 422, 429), r.text
    huge = await http.post("/ai/complete", json={"stage": "summarize", "messages": [{"role": "user", "content": "x" * 20_000}] * 25}, headers=agent)
    assert huge.status_code == 422 and error_shape(huge) == "validation_error"  # above the total size cap (500k > 400k)
