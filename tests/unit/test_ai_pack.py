"""CP-5D-AI: the AI pack, gateway block (D33 LLM gateway).

Spec declaration and validation (incl. the declared documents / knowledge sections), emission only when declared
(existing goldens untouched), tenant treatment, the migration, the generated cost maths and fake provider executed on
hand-computed cases, per-stage routing. Database behaviour (reservation under parallel load, settle / release,
idempotency, zero retention, roles, tenants) is proven by tests/e2e/test_ai_gateway_stack.py."""

import ast
import asyncio
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
from app.core.validation_ai import AI_PRICES, ceil_cost
from app.core.validation_packs import declared_packs

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _raw() -> dict[str, Any]:
    return json.loads((FIXTURES / "ai_gateway_support.json").read_text(encoding="utf-8"))


def _spec(raw: dict[str, Any] | None = None) -> Spec:
    return Spec.model_validate(raw if raw is not None else _raw())


def _codes(raw: dict[str, Any]) -> set[str]:
    return {i.code for i in validate(Spec.model_validate(raw))}


def _gw(raw: dict[str, Any]) -> dict[str, Any]:
    return raw["packs"]["ai"]["gateway"]


def _stage(raw: dict[str, Any], name: str) -> dict[str, Any]:
    return next(s for s in _gw(raw)["stages"] if s["name"] == name)


DOCUMENTS = {
    "kinds": [{"name": "invoice", "fields": [{"name": "total", "required": True}, {"name": "vendor"}]}],
    "stage": "classify",
    "review_roles": ["admin"],
}
KNOWLEDGE = {"stage": "summarize", "manage_roles": ["admin"], "chunk_chars": 800}


# --- the spec ----------------------------------------------------------------------------------------------


def test_the_support_spec_is_valid_and_defaults_apply() -> None:
    assert validate(_spec()) == []
    raw = _raw()
    raw["packs"]["ai"] = {"gateway": {"providers": [{"name": "p", "kind": "fake"}], "stages": [{"name": "s", "provider": "p", "model": "fake-small"}]}}
    gw = _spec(raw).packs.ai.gateway  # type: ignore[union-attr]
    assert gw is not None
    assert (gw.region, gw.zero_retention, gw.budget.period, gw.budget.limit_micro_usd, gw.budget.per_call_cap_micro_usd) == ("eu", False, "day", 1_000_000, 100_000)
    assert gw.roles.call_roles == [] and gw.roles.read_roles == gw.roles.manage_roles == ["admin"]
    assert gw.stages[0].max_output_tokens == 512 and gw.stages[0].fallback_model is None and gw.providers[0].byo_key_env is None
    assert validate(_spec(raw)) == []


@pytest.mark.parametrize(
    "patch",
    [
        {"turbo": True},
        {"zero_retention": "yes"},
        {"budget": {"limit_micro_usd": 1000.5}},
        {"budget": {"limit_micro_usd": "1000"}},
        {"budget": {"per_call_cap_micro_usd": 1.0}},
        {"budget": {"limit_usd": 5}},
        {"stages": [{"name": "x", "provider": "main", "model": "fake-small", "max_output_tokens": 10.5}]},
        {"stages": [{"name": "x", "provider": "main"}]},
        {"providers": [{"name": "p", "kind": "fake", "key": "secret"}]},
        {"roles": {"call_roles": "admin"}},
    ],
)
def test_unknown_options_and_non_integers_are_refused_by_the_spec_model(patch: dict[str, Any]) -> None:
    raw = _raw()
    _gw(raw).update(patch)
    with pytest.raises(ValidationError):
        _spec(raw)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda r: _gw(r).update(providers=[]), "empty"),
        (lambda r: _gw(r)["providers"].append(dict(_gw(r)["providers"][0])), "duplicate"),
        (lambda r: _gw(r)["providers"][0].update(kind="openai"), "unsupported_provider"),
        (lambda r: _gw(r)["providers"][0].update(kind="claude"), "unsupported_provider"),
        (lambda r: _gw(r)["providers"][0].update(byo_key_env="lower case"), "invalid_env_name"),
        (lambda r: _gw(r)["providers"][0].update(name="Bad Name"), "invalid_identifier"),
        (lambda r: _gw(r).update(region="Eu West!"), "invalid_region"),
        (lambda r: _gw(r).update(stages=[]), "empty"),
        (lambda r: _gw(r)["stages"].append(dict(_stage(r, "classify"))), "duplicate"),
        (lambda r: _stage(r, "classify").update(provider="ghost"), "unknown_provider"),
        (lambda r: _stage(r, "classify").update(model="gpt-9"), "unknown_model"),
        (lambda r: _stage(r, "classify").update(fallback_model="gpt-9"), "unknown_model"),
        (lambda r: _stage(r, "classify").update(fallback_model="fake-small"), "same_as_model"),
        (lambda r: _stage(r, "classify").update(name="Bad Stage"), "invalid_identifier"),
        (lambda r: _stage(r, "classify").update(max_output_tokens=0), "out_of_range"),
        (lambda r: _stage(r, "classify").update(max_output_tokens=10**7), "out_of_range"),
        (lambda r: _stage(r, "classify").update(max_output_tokens=300), "stage_above_cap"),
        (lambda r: _gw(r)["budget"].update(period="week"), "invalid_period"),
        (lambda r: _gw(r)["budget"].update(per_call_cap_micro_usd=201), "cap_above_budget"),
        (lambda r: _gw(r)["budget"].update(per_call_cap_micro_usd=0), "out_of_range"),
        (lambda r: _gw(r)["budget"].update(limit_micro_usd=0, per_call_cap_micro_usd=0), "out_of_range"),
        (lambda r: _gw(r)["budget"].update(limit_micro_usd=2**60), "out_of_range"),
        (lambda r: _gw(r)["roles"].update(call_roles=["ghost"]), "unknown_role"),
        (lambda r: _gw(r)["roles"].update(read_roles=["ghost"]), "unknown_role"),
        (lambda r: _gw(r)["roles"].update(manage_roles=[]), "empty"),
        (lambda r: r["packs"]["ai"].clear(), "empty_pack"),
    ],
)
def test_gateway_values_are_validated(mutate: Any, code: str) -> None:
    raw = _raw()
    mutate(raw)
    assert code in _codes(raw)


def test_the_ai_pack_needs_auth_and_rbac() -> None:
    raw = _raw()
    raw["auth"]["enabled"] = False
    assert "needs_auth" in _codes(raw)
    raw = _raw()
    raw["authorization"] = {"model": "abac", "policies": []}
    assert "needs_rbac" in {i.code for i in validate(_spec(raw))}


def test_the_pack_tables_are_reserved_names() -> None:
    for table in ("ai_calls", "ai_budget_periods"):
        raw = _raw()
        raw["entities"][0]["table_name"] = table
        assert any(table in i.message or i.path.endswith("table_name") for i in validate(_spec(raw))), table


# --- the declared documents and knowledge sections (D34, D35) ------------------------------------------------------


def test_documents_and_knowledge_are_declared_and_validated() -> None:
    raw = _raw()
    raw["packs"]["ai"]["documents"] = json.loads(json.dumps(DOCUMENTS))
    raw["packs"]["ai"]["knowledge"] = dict(KNOWLEDGE)
    assert validate(_spec(raw)) == []
    pack = _spec(raw).packs.ai  # type: ignore[union-attr]
    assert pack is not None and pack.documents is not None and pack.knowledge is not None
    assert (pack.documents.review_below_bp, pack.documents.max_text_chars, pack.documents.upload_roles) == (8000, 200_000, [])
    assert (pack.knowledge.chunk_chars, pack.knowledge.max_sources, pack.knowledge.read_roles) == (800, 1000, [])
    assert declared_packs(_spec(raw)) == ("ai.documents", "ai.gateway", "ai.knowledge")
    assert declared_packs(_spec()) == ("ai.gateway",)


@pytest.mark.parametrize(
    ("section", "patch", "code"),
    [
        ("documents", {"stage": "ghost"}, "unknown_stage"),
        ("documents", {"kinds": []}, "empty"),
        ("documents", {"review_below_bp": 10_001}, "out_of_range"),
        ("documents", {"review_roles": []}, "empty"),
        ("documents", {"review_roles": ["ghost"]}, "unknown_role"),
        ("documents", {"kinds": [{"name": "a", "fields": []}]}, "empty"),
        ("documents", {"kinds": [{"name": "a", "fields": [{"name": "x"}, {"name": "x"}]}]}, "duplicate"),
        ("documents", {"kinds": [{"name": "A!", "fields": [{"name": "x"}]}]}, "invalid_identifier"),
        ("knowledge", {"stage": "ghost"}, "unknown_stage"),
        ("knowledge", {"chunk_chars": 10}, "out_of_range"),
        ("knowledge", {"manage_roles": []}, "empty"),
        ("knowledge", {"read_roles": ["ghost"]}, "unknown_role"),
    ],
)
def test_documents_and_knowledge_values_are_validated(section: str, patch: dict[str, Any], code: str) -> None:
    raw = _raw()
    raw["packs"]["ai"][section] = {**(DOCUMENTS if section == "documents" else KNOWLEDGE), **patch}
    assert code in _codes(raw)


def test_documents_and_knowledge_need_the_gateway() -> None:
    raw = _raw()
    del raw["packs"]["ai"]["gateway"]
    raw["packs"]["ai"]["knowledge"] = dict(KNOWLEDGE)
    assert "needs_gateway" in _codes(raw)


@pytest.mark.parametrize("patch", [{"review_below_bp": 80.5}, {"max_text_chars": "10"}, {"auto_approve": True}])
def test_documents_integers_are_strict(patch: dict[str, Any]) -> None:
    raw = _raw()
    raw["packs"]["ai"]["documents"] = {**DOCUMENTS, **patch}
    with pytest.raises(ValidationError):
        _spec(raw)


# --- emission ------------------------------------------------------------------------------------------------


def test_emission_only_when_declared() -> None:
    raw = _raw()
    del raw["packs"]
    plain = generate(_spec(raw))
    assert not [p for p in plain if "/ai/" in p or "ai_gateway" in p]
    assert "_ai_router" not in plain["app/main.py"] and "_ai_models" not in plain["app/models/__init__.py"]
    assert "ai_calls" not in plain["tests/conftest.py"]
    files = generate(_spec())
    assert sorted(p for p in files if "/ai/" in p or "ai_gateway" in p) == [
        "alembic/versions/0038_ai_gateway.py",
        "app/ai/__init__.py",
        "app/ai/config.py",
        "app/ai/models.py",
        "app/ai/providers.py",
        "app/ai/router.py",
        "app/ai/schemas.py",
        "app/ai/service.py",
    ]
    assert "include_router(_ai_router)" in files["app/main.py"] and "_ai_models" in files["app/models/__init__.py"]
    assert "ai_calls" in files["tests/conftest.py"] and "ai_budget_periods" in files["tests/conftest.py"]


def test_a_shared_file_differs_from_a_non_ai_project_only_by_the_ai_lines() -> None:
    raw = _raw()
    del raw["packs"]
    plain, with_ai = generate(_spec(raw)), generate(_spec())
    for path in ("app/main.py", "app/models/__init__.py"):
        extra = [ln for ln in with_ai[path].splitlines() if ln not in plain[path].splitlines()]
        assert extra and all("_ai" in ln for ln in extra), (path, extra)
    shared = {p for p in with_ai if p in plain and with_ai[p] != plain[p]}
    assert shared == {"app/main.py", "app/models/__init__.py", "tests/conftest.py", "platform/zones.json"}  # zones.json lists the files


def test_roles_budget_stages_and_prices_come_from_the_spec() -> None:
    files = generate(_spec())
    cfg = files["app/ai/config.py"]
    assert "CALL_ROLES: tuple[str, ...] = ('admin', 'agent',)" in cfg and "MANAGE_ROLES: tuple[str, ...] = ('admin',)" in cfg
    assert "BUDGET_LIMIT_MICRO_USD = 200" in cfg and "PER_CALL_CAP_MICRO_USD = 100" in cfg and "BUDGET_PERIOD = 'day'" in cfg
    assert "ZERO_RETENTION = False" in cfg and "MULTI_TENANT = True" in cfg and "REGION = 'eu'" in cfg
    assert "'fallback_model': 'fake-embed'" in cfg and "'byo_key_env': 'SUPPORT_AI_KEY'" in cfg and "UNVERIFIED" in cfg
    for model, (price_in, price_out) in AI_PRICES.items():
        assert f"'{model}': ({price_in}, {price_out})" in cfg
    router = files["app/ai/router.py"]
    for route in ('"/complete"', '"/calls"', '"/usage"'):
        assert route in router
    service = files["app/ai/service.py"]
    for needle in ("with_for_update()", "budget_exceeded", "per_call_cap_exceeded", "unknown_stage", "provider_error", "idempotency_conflict"):
        assert needle in service, needle
    raw = _raw()
    _gw(raw)["zero_retention"] = True
    _gw(raw)["budget"]["period"] = "month"
    cfg = generate(_spec(raw))["app/ai/config.py"]
    assert "ZERO_RETENTION = True" in cfg and "BUDGET_PERIOD = 'month'" in cfg


def test_the_migration_has_the_ledger_and_the_locked_budget_row() -> None:
    migration = generate(_spec())["alembic/versions/0038_ai_gateway.py"]
    assert 'revision: str = "0038"' in migration
    for needle in ("ai_calls", "ai_budget_periods", "cost_micro_usd", "sa.BigInteger()", "uq_ai_calls_idempotency_key", "status <> 'error'", "uq_ai_budget_periods_period", "ck_ai_budget_periods_amounts"):
        assert needle in migration, needle
    assert "prompt_text" in migration and "nullable=True" in migration
    assert "sa.Float" not in migration and "sa.Numeric" not in migration


def test_the_migration_is_chained_after_booking_and_every_other_block() -> None:
    both = _raw()
    both["packs"]["booking"] = {"kinds": [{"name": "desk", "mode": "range"}]}
    files = generate(_spec(both))
    assert 'down_revision: str | None = "0037"' in files["alembic/versions/0038_ai_gateway.py"]
    assert "0037_booking.py" in " ".join(files)
    alone = generate(_spec())["alembic/versions/0038_ai_gateway.py"]
    assert 'down_revision: str | None = "0002"' in alone


def test_tenant_treatment_matches_booking_and_single_tenant_has_none() -> None:
    tenant = generate(_spec())
    for path in ("app/ai/models.py", "alembic/versions/0038_ai_gateway.py"):
        assert tenant[path].count('"auth_tenants.id"') >= 2 and 'ondelete="RESTRICT"' in tenant[path], path
    assert tenant["app/ai/service.py"].count("_scoped(") >= 6
    raw = _raw()
    raw["auth"]["multi_tenant"] = False
    for permission in raw["auth"]["permissions"]:
        permission.pop("row_rule", None)
    single = generate(Spec.model_validate(raw))
    for path in ("app/ai/models.py", "alembic/versions/0038_ai_gateway.py"):
        assert "tenant_id" not in single[path] and "auth_tenants" not in single[path], path
    assert "MULTI_TENANT = False" in single["app/ai/config.py"]


def test_the_block_is_registered_with_its_dependencies() -> None:
    assert pack_registry()["ai.gateway"].id == "ai_gateway"
    assert {"crud", "auth"} <= set(pack_registry()["ai.gateway"].depends_on)
    assert module_registry()["ai_gateway"].pack == "ai.gateway"


def test_every_ai_file_parses_and_has_no_float_money() -> None:
    files = generate(_spec())
    for path, content in files.items():
        if path.endswith(".py"):
            ast.parse(content, filename=path)
    for path in ("app/ai/service.py", "app/ai/schemas.py", "app/ai/models.py", "app/ai/config.py", "app/ai/providers.py"):
        tree = ast.parse(files[path])
        assert not [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, float)], path
        assert not [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "float"], path
    assert not ({"app/ai/providers.py"} & {p for p in files if "real" in p})


def test_only_the_fake_provider_exists_in_generated_code() -> None:
    providers = generate(_spec())["app/ai/providers.py"]
    for forbidden in ("httpx", "requests", "urllib", "socket", "anthropic", "openai", "aiohttp"):
        assert forbidden not in providers, forbidden
    assert "not available" in providers


# --- the pure generated pieces, executed -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def gen() -> types.SimpleNamespace:
    """The generated `app.ai.providers` and the pure cost helpers of `app.ai.service`, executed without a database."""
    files = generate(_spec())
    providers = types.ModuleType("app.ai.providers")
    exec(compile(files["app/ai/providers.py"], "app/ai/providers.py", "exec"), providers.__dict__)  # noqa: S102
    config = types.ModuleType("app.ai.config")
    exec(compile(files["app/ai/config.py"], "app/ai/config.py", "exec"), config.__dict__)  # noqa: S102
    # the pure helpers are defined in service.py: lift just those two functions
    tree = ast.parse(files["app/ai/service.py"])
    wanted = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {"cost_micro_usd", "period_start"}]
    module = types.ModuleType("service_pure")
    module.__dict__.update({"_config": config, "UTC": __import__("datetime").UTC, "date": __import__("datetime").date, "datetime": __import__("datetime").datetime})
    exec(compile(ast.Module(body=wanted, type_ignores=[]), "service_pure", "exec"), module.__dict__)  # noqa: S102
    return types.SimpleNamespace(providers=providers, config=config, cost=module.cost_micro_usd, period_start=module.period_start)


def test_cost_maths_is_integer_and_rounds_up(gen: types.SimpleNamespace) -> None:
    assert gen.cost("fake-small", 2, 6) == 1 + 4  # ceil(0.3) + ceil(3.6)
    assert gen.cost("fake-small", 0, 0) == 0
    assert gen.cost("fake-small", 1, 0) == 1  # a single token still costs a whole micro-USD (never under-bills)
    assert gen.cost("fake-small", 1_000_000, 1_000_000) == 150_000 + 600_000
    assert gen.cost("fake-large", 1000, 1000) == 3000 + 15_000
    assert gen.cost("fake-embed", 100, 10_000) == 2  # output is free
    assert gen.cost("fake-large", 10**9, 10**9) == 18_000_000_000 and type(gen.cost("fake-large", 3, 3)) is int
    for model, (p_in, p_out) in AI_PRICES.items():
        assert gen.cost(model, 7, 11) == ceil_cost(7, p_in) + ceil_cost(11, p_out)
    with pytest.raises(KeyError):
        gen.cost("gpt-9", 1, 1)


def test_the_worst_case_is_the_input_estimate_plus_the_output_cap(gen: types.SimpleNamespace) -> None:
    est = gen.providers.estimate_input_tokens
    assert est(["hello"]) == 2 and est(["a", "b"]) == 2 and est(["x" * 2000]) == 500 and est([""]) == 1
    assert gen.cost("fake-small", est(["x" * 2000]), 100) == 75 + 60 == 135  # the per-call cap scenario of the e2e file


def test_the_period_is_a_utc_day_or_month(gen: types.SimpleNamespace) -> None:
    from datetime import UTC, date, datetime, timedelta, timezone

    late = datetime(2026, 12, 31, 23, 30, tzinfo=timezone(timedelta(hours=-5)))  # 2027-01-01 04:30 UTC
    assert gen.period_start(late) == date(2027, 1, 1)
    gen.config.BUDGET_PERIOD = "month"
    try:
        assert gen.period_start(datetime(2026, 11, 13, 8, tzinfo=UTC)) == date(2026, 11, 1)
    finally:
        gen.config.BUDGET_PERIOD = "day"


def _run(gen: types.SimpleNamespace, contents: list[str], **kw: Any) -> Any:
    args: dict[str, Any] = {"kind": "fake", "model": "fake-small", "contents": contents, "max_output_tokens": 100, "json_mode": False, "is_fallback": False, "directives_enabled": True}
    args.update(kw)
    return asyncio.run(gen.providers.complete(**args))


def test_the_fake_provider_is_deterministic_and_counts_tokens(gen: types.SimpleNamespace) -> None:
    a, b = _run(gen, ["hello"]), _run(gen, ["hello"])
    assert a == b and a.text.startswith("fake:") and (a.input_tokens, a.output_tokens) == (2, 6)
    assert _run(gen, ["hello"], model="fake-large").text != a.text and _run(gen, ["hello!"]).text != a.text


def test_the_fake_provider_switches(gen: types.SimpleNamespace) -> None:
    assert _run(gen, ["x [[fake:out=40]]"]).output_tokens == 40
    assert _run(gen, ["x [[fake:out=400]]"], max_output_tokens=100).output_tokens == 100  # capped
    assert _run(gen, ['x [[fake:json={"a": 1}]]'], json_mode=True).text == '{"a": 1}'
    assert json.loads(_run(gen, ["x"], json_mode=True).text)["echo"]
    with pytest.raises(gen.providers.ProviderError):
        _run(gen, ["x [[fake:fail]]"])
    with pytest.raises(gen.providers.ProviderError):
        _run(gen, ["x [[fake:fail_primary]]"])
    assert _run(gen, ["x [[fake:fail_primary]]"], is_fallback=True).text.startswith("fake:")
    with pytest.raises(gen.providers.ProviderError):
        _run(gen, ["hi"], kind="anthropic")


def test_stages_are_routed_by_name(gen: types.SimpleNamespace) -> None:
    stages = gen.config.STAGES
    assert sorted(stages) == ["classify", "summarize"]
    assert stages["classify"] == {"provider": "main", "model": "fake-small", "max_output_tokens": 100, "fallback_model": None}
    assert stages["summarize"]["fallback_model"] == "fake-embed" and gen.config.PROVIDERS["main"]["kind"] == "fake"
    raw = _raw()
    _stage(raw, "classify").update(model="fake-large", max_output_tokens=6)
    raw["packs"]["ai"]["gateway"]["stages"].append({"name": "extra.stage-1", "provider": "main", "model": "fake-small", "max_output_tokens": 7})
    assert validate(_spec(raw)) == []
    routed = generate(_spec(raw))["app/ai/config.py"]
    assert "'model': 'fake-large'" in routed and "'max_output_tokens': 6" in routed and "'extra.stage-1'" in routed
    unused = types.ModuleType("probe")
    exec(compile(routed, "config", "exec"), unused.__dict__)  # noqa: S102
    assert unused.STAGES["classify"]["model"] == "fake-large" and unused.STAGES["summarize"]["model"] == "fake-small"


def test_generation_is_deterministic() -> None:
    assert generate(_spec()) == generate(_spec())
    reordered = _raw()
    _gw(reordered)["stages"].reverse()
    assert generate(_spec(reordered))["app/ai/config.py"] == generate(_spec())["app/ai/config.py"]  # sorted: order does not matter
