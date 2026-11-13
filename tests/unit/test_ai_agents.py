"""CP-5E: the AI pack, agents block (D37 agent runtime). Spec rules and their stable codes, emission only when declared,
migration 0041, tenant treatment, the generated pure parts executed (argument checks, model-output parsing, the dial).
The autonomy dial against a database (every level, every action cap, parallel approvals ...) is proven by
tests/e2e/test_ai_agents_stack.py."""

import ast
import copy
import json
import types
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.generator import generate
from app.core.generator.engine import module_registry, pack_registry
from app.core.spec_models import Spec
from app.core.validation import validate
from app.core.validation_ai import ai_tables
from app.core.validation_packs import declared_packs

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _raw() -> dict[str, Any]:
    return json.loads((FIXTURES / "ai_agents_evals.json").read_text(encoding="utf-8"))


def _codes(raw: dict[str, Any]) -> set[str]:
    return {i.code for i in validate(Spec.model_validate(raw))}


def _ag(raw: dict[str, Any]) -> dict[str, Any]:
    return raw["packs"]["ai"]["agents"]


def _action(raw: dict[str, Any], name: str) -> dict[str, Any]:
    return next(a for a in _ag(raw)["actions"] if a["name"] == name)


def _agent(raw: dict[str, Any], name: str) -> dict[str, Any]:
    return next(a for a in _ag(raw)["agents"] if a["name"] == name)


def _with(mutate: Any) -> set[str]:
    raw = _raw()
    mutate(raw)
    return _codes(raw)


# --- the spec ----------------------------------------------------------------------------------------------


def test_the_fixture_is_valid_and_declares_agents_and_evals() -> None:
    spec = Spec.model_validate(_raw())
    assert validate(spec) == []
    assert declared_packs(spec) == ("ai.agents", "ai.evals", "ai.gateway")
    assert ai_tables(spec) == ("ai_calls", "ai_budget_periods", "ai_agent_runs", "ai_agent_proposals", "ai_eval_runs")
    assert {"ai.agents", "ai.evals"} <= set(pack_registry())
    assert module_registry()["ai_agents"].pack == "ai.agents" and "ai_agents" in module_registry()["ai_evals"].depends_on


def test_defaults_are_the_safest_ones() -> None:
    raw = _raw()
    raw["packs"]["ai"]["agents"] = {
        "actions": [{"name": "n"}],
        "agents": [{"name": "a", "actions": ["n"]}],
    }
    del raw["packs"]["ai"]["evals"]
    spec = Spec.model_validate(raw)
    ag = spec.packs.ai.agents  # type: ignore[union-attr]
    assert ag is not None
    assert (ag.actions[0].kind, ag.actions[0].risk, ag.actions[0].max_autonomy) == ("note", "low", "draft")
    assert (ag.agents[0].autonomy, ag.agents[0].max_actions_per_run, ag.agents[0].require_eval) == ("suggest", 5, None)
    assert ag.roles.run_roles == [] and ag.roles.approve_roles == ["admin"] and ag.roles.read_roles == [] and ag.allow_self_approval is False
    assert validate(spec) == []


def test_unknown_options_and_floats_are_refused_by_the_models() -> None:
    raw = _raw()
    _ag(raw)["agents"][0]["max_actions_per_run"] = 2.5
    with pytest.raises(ValidationError):
        Spec.model_validate(raw)
    raw = _raw()
    _ag(raw)["agents"][0]["tool"] = "shell"
    with pytest.raises(ValidationError):
        Spec.model_validate(raw)
    raw = _raw()
    raw["packs"]["ai"]["evals"]["suites"][0]["pass_bp"] = 80.5
    with pytest.raises(ValidationError):
        Spec.model_validate(raw)


@pytest.mark.parametrize(
    ("code", "mutate"),
    [
        ("unknown_action", lambda r: _agent(r, "watcher")["actions"].append("ghost")),
        ("unknown_stage", lambda r: _agent(r, "watcher").update(stage="ghost")),
        ("unknown_role", lambda r: _ag(r)["roles"].update(approve_roles=["ghost"])),
        ("unknown_role", lambda r: _ag(r)["roles"].update(run_roles=["ghost"])),
        ("unknown_role", lambda r: _ag(r)["roles"].update(read_roles=["ghost"])),
        ("entity_create_not_permitted", lambda r: r["auth"].update(permissions=[p for p in r["auth"]["permissions"] if p["operation"] != "create"])),
        ("unknown_entity", lambda r: _action(r, "open_ticket").update(entity="ghosts")),
        ("unknown_field", lambda r: _action(r, "open_ticket")["fields"].append("ghost")),
        ("unknown_field", lambda r: _action(r, "open_ticket")["fields"].append("created_at")),  # a system column
        ("unknown_field", lambda r: _action(r, "open_ticket")["fields"].append("tenant_id")),
        ("missing_entity", lambda r: _action(r, "open_ticket").update(entity=None)),
        ("required_field_missing", lambda r: _action(r, "open_ticket").update(fields=["priority"])),
        ("empty", lambda r: _action(r, "open_ticket").update(fields=[])),
        ("unexpected_entity", lambda r: _action(r, "add_note").update(entity="tickets")),
        ("unexpected_entity", lambda r: _action(r, "add_note").update(fields=["title"])),
        ("duplicate", lambda r: _ag(r)["actions"].append(dict(_action(r, "add_note")))),
        ("duplicate", lambda r: _ag(r)["agents"].append(dict(_agent(r, "watcher")))),
        ("duplicate", lambda r: _agent(r, "watcher")["actions"].append("add_note")),
        ("invalid_autonomy", lambda r: _agent(r, "watcher").update(autonomy="full")),
        ("invalid_autonomy", lambda r: _action(r, "add_note").update(max_autonomy="root")),
        ("invalid_autonomy", lambda r: _action(r, "add_note").update(max_autonomy="")),
        ("invalid_risk", lambda r: _action(r, "add_note").update(risk="none")),
        ("invalid_kind", lambda r: _action(r, "add_note").update(kind="shell")),
        ("invalid_identifier", lambda r: _action(r, "add_note").update(name="Add Note")),
        ("out_of_range", lambda r: _agent(r, "watcher").update(max_actions_per_run=0)),
        ("out_of_range", lambda r: _agent(r, "watcher").update(max_actions_per_run=21)),
        ("empty", lambda r: _agent(r, "watcher").update(actions=[])),
        ("empty", lambda r: _ag(r).update(agents=[])),
        ("empty", lambda r: _ag(r).update(actions=[])),
        ("empty", lambda r: _ag(r)["roles"].update(approve_roles=[])),
        ("unknown_eval_suite", lambda r: _agent(r, "watcher").update(require_eval="ghost")),
        ("eval_suite_other_agent", lambda r: _agent(r, "watcher").update(require_eval="guarded_basic")),
        ("zero_retention_conflict", lambda r: r["packs"]["ai"]["gateway"].update(zero_retention=True)),
        ("needs_agents", lambda r: r["packs"]["ai"].update(agents=None)),
        ("needs_gateway", lambda r: r["packs"]["ai"].update(gateway=None)),
        # evals
        ("unknown_agent", lambda r: r["packs"]["ai"]["evals"]["suites"][0].update(agent="ghost")),
        ("out_of_range", lambda r: r["packs"]["ai"]["evals"]["suites"][0].update(pass_bp=10001)),
        ("out_of_range", lambda r: r["packs"]["ai"]["evals"]["suites"][0].update(pass_bp=-1)),
        ("out_of_range", lambda r: r["packs"]["ai"]["evals"]["suites"][0].update(pass_bp=0)),
        ("vacuous_case", lambda r: r["packs"]["ai"]["evals"]["suites"][0]["cases"][0].update(expect_actions=[], forbid_actions=[])),
        ("action_not_in_agent", lambda r: r["packs"]["ai"]["evals"]["suites"][0]["cases"][0].update(expect_actions=["escalate"])),
        ("unknown_action", lambda r: r["packs"]["ai"]["evals"]["suites"][0]["cases"][0].update(forbid_actions=["ghost"])),
        ("contradictory_case", lambda r: r["packs"]["ai"]["evals"]["suites"][0]["cases"][0].update(forbid_actions=["add_note"])),
        ("empty", lambda r: r["packs"]["ai"]["evals"]["suites"][0].update(cases=[])),
        ("empty", lambda r: r["packs"]["ai"]["evals"].update(suites=[])),
        ("duplicate", lambda r: r["packs"]["ai"]["evals"]["suites"].append(dict(r["packs"]["ai"]["evals"]["suites"][0]))),
        ("duplicate", lambda r: r["packs"]["ai"]["evals"]["suites"][0]["cases"].append(dict(r["packs"]["ai"]["evals"]["suites"][0]["cases"][0]))),
        ("unknown_role", lambda r: r["packs"]["ai"]["evals"].update(run_roles=["ghost"])),
    ],
)
def test_a_bad_declaration_has_a_stable_code(code: str, mutate: Any) -> None:
    assert code in _with(mutate)


def test_the_boundaries_are_accepted() -> None:
    def edge(raw: dict[str, Any]) -> None:
        _agent(raw, "watcher")["max_actions_per_run"] = 20
        _agent(raw, "drafter")["max_actions_per_run"] = 1
        raw["packs"]["ai"]["evals"]["suites"][0]["pass_bp"] = 1
        raw["packs"]["ai"]["evals"]["suites"][1]["pass_bp"] = 10000

    assert _with(edge) == set()


def test_evals_without_agents_and_agents_without_gateway_are_refused() -> None:
    raw = _raw()
    del raw["packs"]["ai"]["agents"]
    assert "needs_agents" in _codes(raw)
    raw = _raw()
    del raw["packs"]["ai"]["gateway"]
    assert "needs_gateway" in _codes(raw)
    raw = _raw()
    raw["packs"]["ai"] = {}
    assert "empty_pack" in _codes(raw)


def test_agents_need_auth_and_rbac() -> None:
    raw = _raw()
    raw["auth"]["enabled"] = False
    assert "needs_auth" in _codes(raw)


def test_a_suite_of_another_agent_cannot_gate_an_agent_and_a_high_risk_auto_cap_is_legal() -> None:
    raw = _raw()
    assert _action(raw, "escalate")["risk"] == "high" and _action(raw, "escalate")["max_autonomy"] == "auto"
    assert _codes(raw) == set()


# --- emission ----------------------------------------------------------------------------------------------


def _files(raw: dict[str, Any] | None = None) -> dict[str, str]:
    return generate(Spec.model_validate(raw or _raw()))


def test_blocks_are_emitted_only_when_declared() -> None:
    raw = _raw()
    del raw["packs"]["ai"]["evals"]
    for agent in _ag(raw)["agents"]:
        agent["require_eval"] = None
    files = _files(raw)
    assert any("agents" in p for p in files) and not [p for p in files if "evals" in p]
    assert "_ai_evals_router" not in files["app/main.py"] and "evals_models" not in files["app/models/__init__.py"]
    assert "EVALS = False" in files["app/ai/agents_config.py"]
    plain = copy.deepcopy(raw)
    del plain["packs"]["ai"]["agents"]
    plain_files = _files(plain)
    assert not [p for p in plain_files if "agents" in p or "evals" in p]
    assert "_ai_agents_router" not in plain_files["app/main.py"]
    for table in ("ai_agent_runs", "ai_agent_proposals", "ai_eval_runs"):
        assert table not in plain_files["tests/conftest.py"]


def test_the_files_wiring_and_conftest() -> None:
    files = _files()
    for path in (
        "app/ai/agents_config.py",
        "app/ai/agents_models.py",
        "app/ai/agents_schemas.py",
        "app/ai/agents_service.py",
        "app/ai/agents_router.py",
        "alembic/versions/0041_ai_agents.py",
        "app/ai/evals_config.py",
        "alembic/versions/0042_ai_evals.py",
    ):
        assert path in files
    main, models = files["app/main.py"], files["app/models/__init__.py"]
    assert "include_router(_ai_agents_router)" in main and "include_router(_ai_evals_router)" in main
    assert "agents_models" in models and "evals_models" in models
    for table in ("ai_agent_runs", "ai_agent_proposals", "ai_eval_runs"):
        assert f" {table}," in files["tests/conftest.py"]
    assert 'down_revision: str | None = "0038"' in files["alembic/versions/0041_ai_agents.py"]
    assert files["alembic/versions/0042_ai_evals.py"].count('down_revision: str | None = "0041"') == 1


def test_the_config_carries_the_registry_the_dial_and_the_writable_fields() -> None:
    config = _files()["app/ai/agents_config.py"]
    ns: dict[str, Any] = {}
    exec(compile(config, "agents_config", "exec"), ns)  # noqa: S102
    assert ns["RANK"] == {"suggest": 0, "draft": 1, "auto": 2}
    assert ns["ALLOW_SELF_APPROVAL"] is False and ns["EVALS"] is True
    assert ns["APPROVE_ROLES"] == ("admin",) and ns["RUN_ROLES"] == ("admin", "agent")
    assert set(ns["ACTIONS"]) == {"add_note", "escalate", "note_draft", "note_suggest", "open_ticket"}
    assert ns["ACTIONS"]["open_ticket"]["fields"] == ["title", "priority"] and ns["ACTIONS"]["escalate"]["risk"] == "high"
    assert ns["AGENTS"]["guarded"]["require_eval"] == "guarded_basic" and ns["AGENTS"]["watcher"]["autonomy"] == "suggest"
    assert ns["ENTITIES"]["tickets"]["title"]["required"] is True and ns["ENTITIES"]["tickets"]["priority"]["max"] == 5
    assert "admin" in ns["KNOWN_ROLES"]


def test_the_migration_and_tenant_treatment() -> None:
    files = _files()
    migration = files["alembic/versions/0041_ai_agents.py"]
    for needle in ("ai_agent_runs", "ai_agent_proposals", "uq_ai_agent_runs_idempotency_key", "ck_ai_agent_proposals_status", "ck_ai_agent_proposals_outcome", "tenant_id", "JSONB", "rejected_by_policy"):
        assert needle in migration, needle
    assert "tenant_id" in files["app/ai/agents_models.py"] and "tenant_id" in files["alembic/versions/0042_ai_evals.py"]
    raw = _raw()
    raw["auth"]["multi_tenant"] = False
    for perm in raw["auth"]["permissions"]:
        perm.pop("row_rule", None)
    single = _files(raw)
    for path in ("app/ai/agents_models.py", "alembic/versions/0041_ai_agents.py", "alembic/versions/0042_ai_evals.py", "app/ai/evals_models.py"):
        assert "tenant_id" not in single[path] and "auth_tenants" not in single[path], path


def test_every_agents_file_parses_and_the_model_is_reached_only_through_the_gateway() -> None:
    files = _files()
    for path, content in files.items():
        if path.endswith(".py"):
            ast.parse(content, filename=path)
    service = files["app/ai/agents_service.py"]
    assert "_gateway.complete(" in service
    for forbidden in ("providers.complete", "httpx", "requests", "urllib", "socket", "anthropic", "openai", "import providers"):
        assert forbidden not in service and forbidden not in files["app/ai/evals_service.py"], forbidden
    assert "from app.ai import providers" not in service
    # the stored prompt text never reaches a response model
    schemas = files["app/ai/agents_schemas.py"]
    assert "prompt_text" not in schemas and "output_text" not in schemas and "prompt_hash" not in schemas
    assert "FAKE_DIRECTIVES = False" in files["app/ai/config.py"]


def test_the_execution_path_checks_the_dial_itself() -> None:
    service = _files()["app/ai/agents_service.py"]
    execute = service[service.index("async def _execute(") : service.index("# --- prompt and model output")]
    assert "RANK[ceiling] < RANK[required]" in execute and "autonomy_refuses_execution" in execute and 'action["risk"] == "high"' in execute
    approve = service[service.index("async def approve(") : service.index("async def reject(")]
    assert "_lock(" in approve and '"draft"' in approve  # approve needs the draft rank, under the row lock


# --- the pure generated pieces, executed -------------------------------------------------------------------


@pytest.fixture(scope="module")
def gen() -> types.SimpleNamespace:
    files = _files()
    config = types.ModuleType("agents_config")
    exec(compile(files["app/ai/agents_config.py"], "agents_config", "exec"), config.__dict__)  # noqa: S102
    tree = ast.parse(files["app/ai/agents_service.py"])
    wanted = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {"_coerce", "_check_args", "_parse_actions", "_low", "_no_nul"}]
    import datetime
    import decimal
    import math
    import typing
    import uuid

    class AppError(Exception):
        def __init__(self, code: str, message: str, status: int = 400, details: Any = None) -> None:
            self.code = code

    module = types.ModuleType("pure")
    module.__dict__.update(
        {"_config": config, "_t": typing, "json": json, "math": math, "_uuid": uuid, "Decimal": decimal.Decimal, "InvalidOperation": decimal.InvalidOperation,
         "UTC": datetime.UTC, "date": datetime.date, "datetime": datetime.datetime, "RANK": config.RANK, "MAX_PROPOSALS_PER_RUN": 50, "AppError": AppError}
    )
    exec(compile(ast.Module(body=wanted, type_ignores=[]), "pure", "exec"), module.__dict__)  # noqa: S102
    providers = types.ModuleType("providers")
    exec(compile(files["app/ai/providers.py"], "providers", "exec"), providers.__dict__)  # noqa: S102
    return types.SimpleNamespace(config=config, m=module, providers=providers)


def test_the_dial_is_the_minimum_of_the_levels(gen: types.SimpleNamespace) -> None:
    levels = ("suggest", "draft", "auto")
    for a in levels:
        for b in levels:
            for c in levels:
                assert gen.m._low(a, b, c) == levels[min(levels.index(a), levels.index(b), levels.index(c))]


def test_note_arguments_are_exactly_text(gen: types.SimpleNamespace) -> None:
    note = gen.config.ACTIONS["add_note"]
    assert gen.m._check_args(note, {"text": "hi"}) == ({"text": "hi"}, None)
    for bad, reason in (({"text": "hi", "x": 1}, "args_not_allowed"), ({}, "invalid_args"), ({"text": "  "}, "invalid_args"), ({"text": 5}, "invalid_args"), ({"text": "x" * 2001}, "invalid_args")):
        assert gen.m._check_args(note, bad) == (None, reason)
    assert gen.m._check_args(note, {"text": "x" * 5000}) == (None, "args_too_large")


def test_entity_arguments_are_allow_listed_and_typed(gen: types.SimpleNamespace) -> None:
    ticket = gen.config.ACTIONS["open_ticket"]
    check = gen.m._check_args
    assert check(ticket, {"title": "Bug"}) == ({"title": "Bug"}, None)
    assert check(ticket, {"title": "Bug", "priority": 3}) == ({"title": "Bug", "priority": 3}, None)
    assert check(ticket, {"title": "Bug", "tenant_id": "x"}) == (None, "args_not_allowed")  # outside the allow-list
    assert check(ticket, {"title": "Bug", "id": "x"}) == (None, "args_not_allowed")
    assert check(ticket, {"priority": 2}) == (None, "missing_args")
    assert check(ticket, {"title": None}) == (None, "missing_args")
    assert check(ticket, {"title": 5}) == (None, "invalid_args")
    assert check(ticket, {"title": "x" * 121}) == (None, "invalid_args")
    assert check(ticket, {"title": "ok" * 60}) == ({"title": "ok" * 60}, None)  # 120 = the limit
    assert check(ticket, {"title": "Bug", "priority": True}) == (None, "invalid_args")  # a bool is not an integer
    assert check(ticket, {"title": "Bug", "priority": "3"}) == (None, "invalid_args")
    assert check(ticket, {"title": "Bug", "priority": 6}) == (None, "invalid_args")
    assert check(ticket, {"title": "Bug", "priority": 0}) == (None, "invalid_args")
    assert check(ticket, {"title": "Bug", "priority": 5})[1] is None and check(ticket, {"title": "Bug", "priority": 1})[1] is None


def test_coerce_is_strict_for_every_type(gen: types.SimpleNamespace) -> None:
    def rule(kind: str, **extra: Any) -> dict[str, Any]:
        return {"type": kind, "required": False, "max_length": None, "enum": None, "min": None, "max": None, **extra}

    coerce = gen.m._coerce
    assert coerce(rule("boolean"), True) is True
    assert coerce(rule("decimal"), "12.50") == __import__("decimal").Decimal("12.50")
    assert coerce(rule("date"), "2026-01-31").isoformat() == "2026-01-31"
    assert coerce(rule("datetime"), "2026-01-31T10:00:00").tzinfo is not None
    assert str(coerce(rule("uuid"), "00000000-0000-0000-0000-000000000001")).endswith("0001")
    assert coerce(rule("enum", enum=["a", "b"]), "a") == "a"
    assert coerce(rule("json"), {"a": [1]}) == {"a": [1]}
    assert coerce(rule("float"), 1.5) == 1.5
    for kind, value in (
        ("boolean", 1), ("integer", 1.5), ("integer", "1"), ("float", True), ("float", float("nan")), ("decimal", 1.5), ("decimal", "NaN"),
        ("date", 5), ("date", "not-a-date"), ("uuid", "x"), ("enum", "c"), ("string", None), ("file", "x"), ("json", object()),
    ):
        with pytest.raises((ValueError, TypeError)):
            coerce(rule(kind, enum=["a", "b"] if kind == "enum" else None), value)


def test_model_output_parsing(gen: types.SimpleNamespace) -> None:
    parse = gen.m._parse_actions
    assert parse({"actions": []}) == []
    assert parse({"actions": [{"name": "add_note", "args": {"text": "a"}}, {"name": "x"}]}) == [("add_note", {"text": "a"}), ("x", {})]
    assert parse({"actions": [{"name": "x", "args": None}]}) == [("x", {})]
    for bad in (None, [], "text", {"echo": "abc"}, {"actions": "x"}, {"actions": [1]}, {"actions": [{"args": {}}]}, {"actions": [{"name": 5}]},
                {"actions": [{"name": "x", "args": []}]}, {"actions": [{"name": "x", "args": {"a": float("nan")}}]},
                {"actions": [{"name": "x", "args": {"a": "bad\x00nul"}}]}, {"actions": [{"name": "x\x00"}]}):
        assert parse(bad) is None, bad
    assert len(parse({"actions": [{"name": "x"}] * 500})) == 50  # a hostile model cannot make a run write thousands of rows


def test_nul_is_refused_before_the_database(gen: types.SimpleNamespace) -> None:
    gen.m._no_nul("fine", None)
    with pytest.raises(Exception):  # noqa: B017
        gen.m._no_nul("a\x00b")


def test_the_fake_provider_directive_may_carry_a_json_array_and_stays_off_by_default(gen: types.SimpleNamespace) -> None:
    text = 'angry [[fake:json={"actions":[{"name":"add_note","args":{"text":"hi"}}]}]]'
    assert gen.providers._directives([text])["json"] == '{"actions":[{"name":"add_note","args":{"text":"hi"}}]}'
    import asyncio

    on = asyncio.run(gen.providers.complete("fake", "fake-small", [text], 512, True, False, True))
    assert json.loads(on.text) == {"actions": [{"name": "add_note", "args": {"text": "hi"}}]}
    off = asyncio.run(gen.providers.complete("fake", "fake-small", [text], 512, True, False, False))
    assert "actions" not in json.loads(off.text)  # directives off: the text cannot author the output
    config = _files()["app/ai/config.py"]
    assert "FAKE_DIRECTIVES = False" in config


def test_hostile_unclosed_directives_cost_linear_time(gen: types.SimpleNamespace) -> None:
    import time

    started = time.perf_counter()
    gen.providers._directives(["[[fake:a=" * 2200] * 50)
    assert time.perf_counter() - started < 2.0
