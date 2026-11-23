"""Scenario tests for the AI pack, evals block (D38) in the generated `ai_agents_evals` project (copied into the project's tests/
by tests/e2e/test_ai_evals_stack.py, run against a real Postgres). FAKE provider only, no network.

Suites: guarded_basic (agent guarded, pass 10000, 2 cases), drafter_mixed (agent drafter, pass 5000, one case passes and one expects
an action nobody proposes), autopilot_strict (agent autopilot, pass 10000, one case proposes a forbidden action).
Proves: every case runs the agent in DRY mode through the gateway (ledger rows, budget) and nothing executes; the eval rows are
hidden from the inbox, runs, proposals and statistics; scoring in basis points (score = passed * 10000 // total, passed = score >=
pass_bp, both sides of the threshold); an expected action that policy rejected does not count; a forbidden one does fail the case;
a gateway failure on a case is an error that counts as failed and does not stop the suite; the history (newest first, filter,
paging); roles; tenant isolation; no 500 anywhere."""

import json

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient, Response

from app.ai import config as ai_config
from app.ai import evals_config
from app.db import session_factory
from app.main import app
from tests._auth_support import outbox, sign_in  # noqa: F401


@pytest.fixture(autouse=True)
def _fake_directives(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(ai_config, "FAKE_DIRECTIVES", True)


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def people(http: AsyncClient) -> dict[str, dict[str, str]]:
    return {
        "admin": await sign_in(http, "a@example.com", roles=["admin"], n=0),
        "admin2": await sign_in(http, "a_admin2@example.com", roles=["admin"], n=1, join="a@example.com"),
        "agent": await sign_in(http, "a_agent@example.com", roles=["agent"], n=2, join="a@example.com"),
        "customer": await sign_in(http, "a_c@example.com", roles=["customer"], n=3, join="a@example.com"),
        "b_admin": await sign_in(http, "b@example.com", roles=["admin"], n=4),
    }


def goal(*actions: tuple[str, dict]) -> str:
    return "eval case [[fake:json=" + json.dumps({"actions": [{"name": n, "args": a} for n, a in actions]}, separators=(",", ":")) + "]]"


def error_code(r: Response) -> str:
    body = r.json()
    assert set(body) == {"code", "message", "details"} and isinstance(body["details"], list), body
    return body["code"]


async def rows(sql: str, **params: object) -> list[sa.Row]:
    async with session_factory() as session:
        return list((await session.execute(sa.text(sql), params)).all())


async def count(table: str) -> int:
    return int((await rows(f"SELECT count(*) FROM {table}"))[0][0])


async def run_suite(http: AsyncClient, who: dict[str, str], suite: str) -> dict:
    r = await http.post(f"/ai/evals/suites/{suite}/run", headers=who)
    assert r.status_code == 201, r.text
    return r.json()


def adhoc(monkeypatch, agent: str, cases: list[dict], pass_bp: int = 10000) -> None:  # noqa: ANN001
    """A suite that exists only in this test (the spec cannot name a case the agent cannot satisfy)."""
    full = [{"name": c["name"], "goal": c["goal"], "expect_actions": c.get("expect", []), "forbid_actions": c.get("forbid", [])} for c in cases]
    monkeypatch.setitem(evals_config.SUITES, "adhoc", {"agent": agent, "pass_bp": pass_bp, "cases": full})


# --- suites and roles ----------------------------------------------------------------------------------------------


async def test_suites_are_listed_with_their_latest_run(http, people) -> None:  # noqa: ANN001
    listed = (await http.get("/ai/evals/suites", headers=people["admin"])).json()
    assert listed == [
        {"name": "autopilot_strict", "agent": "autopilot", "pass_bp": 10000, "case_count": 2, "latest": None},
        {"name": "drafter_mixed", "agent": "drafter", "pass_bp": 5000, "case_count": 2, "latest": None},
        {"name": "guarded_basic", "agent": "guarded", "pass_bp": 10000, "case_count": 2, "latest": None},
    ]
    run = await run_suite(http, people["admin"], "guarded_basic")
    again = await run_suite(http, people["admin"], "guarded_basic")
    suites = {s["name"]: s for s in (await http.get("/ai/evals/suites", headers=people["admin"])).json()}
    assert suites["guarded_basic"]["latest"] == {"id": again["id"], "passed": True, "score_bp": 10000, "created_at": again["created_at"]}
    assert suites["drafter_mixed"]["latest"] is None and run["id"] != again["id"]


async def test_roles_for_running_and_reading(http, people) -> None:  # noqa: ANN001
    for who in ("admin", "admin2"):
        assert (await http.post("/ai/evals/suites/drafter_mixed/run", headers=people[who])).status_code == 201
    for who in ("agent", "customer"):  # a run-only caller of agents may not run evals; a caller without any role may not do anything
        r = await http.post("/ai/evals/suites/drafter_mixed/run", headers=people[who])
        assert r.status_code == 403 and error_code(r) == "forbidden", who
    assert (await http.get("/ai/evals/suites", headers=people["agent"])).status_code == 200  # agents' run roles may read
    assert (await http.get("/ai/evals/runs", headers=people["agent"])).status_code == 200
    for url in ("/ai/evals/suites", "/ai/evals/runs"):
        r = await http.get(url, headers=people["customer"])
        assert r.status_code == 403 and error_code(r) == "forbidden", url
        assert (await http.get(url)).status_code == 401
    assert (await http.post("/ai/evals/suites/drafter_mixed/run")).status_code == 401
    assert await count("ai_eval_runs") == 2  # only the two allowed runs left a row


async def test_an_unknown_suite_and_bad_ids_are_clean_errors(http, people) -> None:  # noqa: ANN001
    r = await http.post("/ai/evals/suites/ghost/run", headers=people["admin"])
    assert r.status_code == 404 and error_code(r) == "unknown_suite"
    assert await count("ai_calls") == 0 and await count("ai_eval_runs") == 0
    for url, status in (("/ai/evals/runs/not-a-uuid", 422), ("/ai/evals/runs/00000000-0000-0000-0000-000000000000", 404), ("/ai/evals/runs?limit=0", 422),
                        ("/ai/evals/runs?limit=201", 422), ("/ai/evals/runs?offset=-1", 422)):
        assert (await http.get(url, headers=people["admin"])).status_code == status, url
    assert (await http.post("/ai/evals/suites/" + "x" * 41 + "/run", headers=people["admin"])).status_code == 422


# --- running and scoring ---------------------------------------------------------------------------------------------


async def test_a_run_scores_every_case_through_the_gateway_and_executes_nothing(http, people) -> None:  # noqa: ANN001
    run = await run_suite(http, people["admin"], "guarded_basic")
    assert (run["suite"], run["agent"], run["total"], run["passed_count"], run["score_bp"], run["passed"]) == ("guarded_basic", "guarded", 2, 2, 10000, True)
    assert run["results"] == [
        {"case": "adds note", "passed": True, "proposed": ["add_note"], "error_code": None},
        {"case": "opens ticket", "passed": True, "proposed": ["open_ticket"], "error_code": None},
    ]
    assert run["created_by"] == str((await rows("SELECT id FROM auth_users WHERE email = 'a@example.com'"))[0][0])
    assert (await http.get(f"/ai/evals/runs/{run['id']}", headers=people["agent"])).json() == run
    # two model calls, through the gateway, with cost: the budget applies to evals too
    calls = await rows("SELECT status, stage, cost_micro_usd, prompt_text FROM ai_calls ORDER BY created_at")
    assert [(c.status, c.stage) for c in calls] == [("ok", "answer")] * 2 and all(c.cost_micro_usd > 0 and c.prompt_text is None for c in calls)
    usage = (await http.get("/ai/usage", headers=people["admin"])).json()
    assert usage["calls_ok"] == 2 and usage["spent_micro_usd"] == sum(c.cost_micro_usd for c in calls)
    # dry: the guarded agent is `auto`, yet nothing ran: no ticket, every proposal only `suggested`, flagged eval
    assert await count("tickets") == 0
    flagged = await rows("SELECT status, eval, started_by IS NOT NULL FROM ai_agent_proposals")
    assert [tuple(r) for r in flagged] == [("suggested", True, True)] * 2
    assert [r[0] for r in await rows("SELECT eval FROM ai_agent_runs")] == [True, True]


async def test_the_dry_runs_are_hidden_from_the_inbox_runs_and_statistics(http, people) -> None:  # noqa: ANN001
    await run_suite(http, people["admin"], "autopilot_strict")
    ids = await rows("SELECT r.id AS run_id, p.id AS proposal_id FROM ai_agent_runs r JOIN ai_agent_proposals p ON p.run_id = r.id")
    assert len(ids) == 2
    for who in ("admin", "admin2", "agent"):
        h = people[who]
        for url in ("/ai/agents/runs", "/ai/agents/proposals", "/ai/agents/proposals?status=suggested", "/ai/agents/proposals?status=pending_approval"):
            body = (await http.get(url, headers=h)).json()
            assert body["items"] == [] and body["total"] == 0, (who, url)
        stats = (await http.get("/ai/agents/stats", headers=h)).json()["agents"]
        assert all(a["runs"] == 0 and a["proposals"] == 0 for a in stats), who
    for run_id, proposal_id in ids:
        assert (await http.get(f"/ai/agents/runs/{run_id}", headers=people["admin"])).status_code == 404
        assert (await http.get(f"/ai/agents/proposals/{proposal_id}", headers=people["admin"])).status_code == 404
        for verb, body in (("approve", {}), ("reject", {}), ("acknowledge", {}), ("outcome", {"outcome": "success"})):
            r = await http.post(f"/ai/agents/proposals/{proposal_id}/{verb}", json=body, headers=people["admin2"])
            assert r.status_code == 404, verb
    assert {r[0] for r in await rows("SELECT status FROM ai_agent_proposals")} == {"suggested"}  # untouched
    # a real run next to them is the only thing the inbox shows
    real = await http.post("/ai/agents/drafter/runs", json={"goal": goal(("note_draft", {"text": "x"}))}, headers=people["agent"])
    assert real.status_code == 201
    assert (await http.get("/ai/agents/proposals?status=pending_approval", headers=people["admin"])).json()["total"] == 1


async def test_scoring_is_integer_basis_points_with_a_threshold(http, people, monkeypatch) -> None:  # noqa: ANN001
    mixed = await run_suite(http, people["admin"], "drafter_mixed")  # one of two cases passes: 5000, the suite passes at 5000
    assert (mixed["total"], mixed["passed_count"], mixed["score_bp"], mixed["passed"]) == (2, 1, 5000, True)
    assert mixed["results"] == [
        {"case": "proposes a note", "passed": True, "proposed": ["add_note"], "error_code": None},
        {"case": "expects a ticket nobody proposes", "passed": False, "proposed": ["add_note"], "error_code": None},
    ]
    strict = await run_suite(http, people["admin"], "autopilot_strict")  # the same score below its threshold of 10000
    assert (strict["score_bp"], strict["passed"], strict["passed_count"]) == (5000, False, 1)
    assert strict["results"][1] == {"case": "forbidden escalate", "passed": False, "proposed": ["escalate"], "error_code": None}
    monkeypatch.setitem(evals_config.SUITES["drafter_mixed"], "pass_bp", 5001)  # one basis point above the score
    assert (await run_suite(http, people["admin"], "drafter_mixed"))["passed"] is False
    monkeypatch.setitem(evals_config.SUITES["drafter_mixed"], "pass_bp", 5000)
    assert (await run_suite(http, people["admin"], "drafter_mixed"))["passed"] is True
    monkeypatch.setitem(evals_config.SUITES["drafter_mixed"], "pass_bp", 0)
    assert (await run_suite(http, people["admin"], "drafter_mixed"))["passed"] is True
    # a floor division, never a float: 1 of 3 is 3333
    ok = {"name": "ok", "goal": goal(("add_note", {"text": "n"})), "expect": ["add_note"]}
    bad1 = {"name": "bad1", "goal": goal(("add_note", {"text": "n"})), "expect": ["open_ticket"]}
    bad2 = {"name": "bad2", "goal": goal(("add_note", {"text": "n"})), "forbid": ["add_note"]}
    adhoc(monkeypatch, "drafter", [ok, bad1, bad2], pass_bp=3333)
    third = await run_suite(http, people["admin"], "adhoc")
    assert (third["total"], third["passed_count"], third["score_bp"], third["passed"]) == (3, 1, 3333, True)
    adhoc(monkeypatch, "drafter", [ok, bad1, bad2], pass_bp=3334)
    assert (await run_suite(http, people["admin"], "adhoc"))["passed"] is False
    adhoc(monkeypatch, "drafter", [ok], pass_bp=10000)
    assert (await run_suite(http, people["admin"], "adhoc"))["score_bp"] == 10000


async def test_what_counts_as_a_passing_case(http, people, monkeypatch) -> None:  # noqa: ANN001
    cases = [
        {"name": "expected but rejected by policy", "goal": goal(("escalate", {"text": "x"})), "expect": ["escalate"]},  # guarded does not list escalate
        {"name": "forbidden and rejected", "goal": goal(("escalate", {"text": "x"})), "forbid": ["escalate"]},  # still proposed: fails
        {"name": "expected with bad arguments", "goal": goal(("open_ticket", {"title": 5})), "expect": ["open_ticket"]},  # rejected by policy
        {"name": "nothing expected nothing forbidden", "goal": goal(("add_note", {"text": "n"}))},
        {"name": "empty answer", "goal": goal()},
        {"name": "every expected one", "goal": goal(("add_note", {"text": "n"}), ("open_ticket", {"title": "t"})), "expect": ["add_note", "open_ticket"]},
        {"name": "one of two expected", "goal": goal(("add_note", {"text": "n"})), "expect": ["add_note", "open_ticket"]},
        {"name": "forbidden absent", "goal": goal(("add_note", {"text": "n"})), "forbid": ["open_ticket", "escalate"]},
    ]
    adhoc(monkeypatch, "guarded", cases)
    run = await run_suite(http, people["admin"], "adhoc")
    assert [r["passed"] for r in run["results"]] == [False, False, False, True, True, True, False, True]
    assert run["results"][0]["proposed"] == ["escalate"] and run["results"][4]["proposed"] == []
    assert (run["passed_count"], run["total"], run["score_bp"], run["passed"]) == (4, 8, 5000, False)
    assert await count("tickets") == 0


async def test_a_gateway_failure_on_a_case_is_an_error_and_the_suite_goes_on(http, people, monkeypatch) -> None:  # noqa: ANN001
    cases = [
        {"name": "fine", "goal": goal(("add_note", {"text": "n"})), "expect": ["add_note"]},
        {"name": "provider down", "goal": "x [[fake:fail]]"},
        {"name": "not json", "goal": "x [[fake:json=not json]]"},
        {"name": "no actions key", "goal": 'x [[fake:json={"nonsense":1}]]'},
        {"name": "fine again", "goal": goal(("add_note", {"text": "n"})), "expect": ["add_note"]},
    ]
    adhoc(monkeypatch, "drafter", cases, pass_bp=4000)
    run = await run_suite(http, people["admin"], "adhoc")
    assert [(r["passed"], r["error_code"], r["proposed"]) for r in run["results"]] == [
        (True, None, ["add_note"]),
        (False, "provider_error", []),
        (False, "invalid_output", []),
        (False, "invalid_output", []),
        (True, None, ["add_note"]),
    ]
    assert (run["total"], run["passed_count"], run["score_bp"], run["passed"]) == (5, 2, 4000, True)  # the errors count as failed
    ledger = {r[0]: r[1] for r in await rows("SELECT status, count(*) FROM ai_calls GROUP BY status")}
    assert ledger == {"ok": 3, "error": 2}  # provider_error and the unreadable JSON are ledger rows


async def test_the_budget_applies_to_evals(http, people, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(ai_config, "BUDGET_LIMIT_MICRO_USD", 1)
    run = await run_suite(http, people["admin"], "guarded_basic")  # the suite still finishes: every case is an error
    assert [r["error_code"] for r in run["results"]] == ["budget_exceeded"] * 2
    assert (run["passed"], run["score_bp"], run["passed_count"]) == (False, 0, 0)
    assert await count("ai_calls") == 0 and await count("ai_agent_runs") == 0


async def test_directives_off_every_case_fails_and_an_oversized_suite_is_still_one_run(http, people, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(ai_config, "FAKE_DIRECTIVES", False)
    run = await run_suite(http, people["admin"], "guarded_basic")
    assert (run["score_bp"], run["passed"]) == (0, False) and [r["error_code"] for r in run["results"]] == ["invalid_output"] * 2
    assert await count("ai_eval_runs") == 1


# --- history and tenants ---------------------------------------------------------------------------------------------


async def test_the_history_is_newest_first_filtered_and_paged(http, people) -> None:  # noqa: ANN001
    first = await run_suite(http, people["admin"], "drafter_mixed")
    second = await run_suite(http, people["admin"], "guarded_basic")
    third = await run_suite(http, people["admin2"], "drafter_mixed")
    body = (await http.get("/ai/evals/runs", headers=people["agent"])).json()
    assert [r["id"] for r in body["items"]] == [third["id"], second["id"], first["id"]] and body["total"] == 3
    assert body["items"][0] == third
    only_mixed = (await http.get("/ai/evals/runs?suite=drafter_mixed", headers=people["admin"])).json()
    assert [r["id"] for r in only_mixed["items"]] == [third["id"], first["id"]] and only_mixed["total"] == 2
    page = (await http.get("/ai/evals/runs?limit=1&offset=1", headers=people["admin"])).json()
    assert [r["id"] for r in page["items"]] == [second["id"]] and (page["total"], page["limit"], page["offset"]) == (3, 1, 1)
    assert (await http.get("/ai/evals/runs?suite=ghost", headers=people["admin"])).json() == {"items": [], "total": 0, "limit": 50, "offset": 0}
    suites = {s["name"]: s for s in (await http.get("/ai/evals/suites", headers=people["admin"])).json()}
    assert suites["drafter_mixed"]["latest"]["id"] == third["id"]  # the newest run is the latest


async def test_another_tenant_sees_and_changes_nothing(http, people) -> None:  # noqa: ANN001
    mine = await run_suite(http, people["admin"], "guarded_basic")
    b = people["b_admin"]
    r = await http.get(f"/ai/evals/runs/{mine['id']}", headers=b)
    assert r.status_code == 404 and error_code(r) == "not_found"
    assert (await http.get("/ai/evals/runs", headers=b)).json()["items"] == []
    assert all(s["latest"] is None for s in (await http.get("/ai/evals/suites", headers=b)).json())
    theirs = await run_suite(http, b, "guarded_basic")
    assert theirs["id"] != mine["id"]
    assert (await http.get(f"/ai/evals/runs/{theirs['id']}", headers=people["admin"])).status_code == 404
    assert (await http.get("/ai/evals/runs", headers=people["admin"])).json()["total"] == 1
    # each tenant spent its own budget
    assert (await http.get("/ai/usage", headers=b)).json()["calls_ok"] == 2 and (await http.get("/ai/usage", headers=people["admin"])).json()["calls_ok"] == 2
    tenants = {r[0] for r in await rows("SELECT DISTINCT tenant_id FROM ai_eval_runs")}
    assert len(tenants) == 2


async def test_runs_with_an_identical_created_at_order_by_insertion(http, people) -> None:  # noqa: ANN001
    admin = people["admin"]
    made = [(await run_suite(http, admin, "guarded_basic"))["id"] for _ in range(5)]
    await rows_exec("UPDATE ai_eval_runs SET created_at = '2030-01-01T00:00:00+00'")
    by_seq = [str(r[0]) for r in await rows("SELECT id FROM ai_eval_runs ORDER BY seq DESC")]
    assert sorted(by_seq) == sorted(made) and by_seq == made[::-1]  # seq follows insertion, the random uuid does not
    listed = (await http.get("/ai/evals/runs", headers=admin)).json()["items"]
    assert [r["id"] for r in listed] == by_seq
    suites = {s["name"]: s for s in (await http.get("/ai/evals/suites", headers=admin)).json()}
    assert suites["guarded_basic"]["latest"]["id"] == made[-1]


async def rows_exec(sql: str) -> None:
    async with session_factory() as session:
        await session.execute(sa.text(sql))
        await session.commit()
