"""`settings.<key>` in expressions: typed from the spec, read-only, refused where it cannot work."""

from decimal import Decimal

import pytest

from app.core.expr import ExprError, canonical, check_scoped, compile_python, rewrite_settings, settings_used, to_sql
from app.core.validation_behavior import check_expression

FIELDS = {"amount": ("decimal", False), "days": ("int", True), "note": ("string", True)}
SETTINGS = {"limit": ("int", False), "rate": ("decimal", False), "strict": ("bool", False), "label": ("string", False)}


def typed(text: str):  # noqa: ANN201
    return check_scoped(text, FIELDS, SETTINGS)


def test_the_setting_gets_the_type_the_spec_declares() -> None:
    assert typed("settings.limit")["t"] == "int"
    assert typed("settings.rate")["t"] == "decimal"
    assert typed("settings.strict")["t"] == "bool"
    assert typed("settings.label")["t"] == "string"
    assert typed("amount <= settings.limit")["t"] == "bool"
    assert typed("amount * settings.rate")["t"] == "decimal"
    assert settings_used(typed("amount <= settings.limit and days > settings.limit and settings.strict")) == {"limit", "strict"}


def test_the_type_checker_applies_to_settings_like_to_fields() -> None:
    with pytest.raises(ExprError, match="cannot compare string with int"):
        typed("settings.label == settings.limit")
    with pytest.raises(ExprError, match="needs bool"):
        typed("settings.limit and true")
    with pytest.raises(ExprError, match="int / int"):
        typed("days / settings.limit")


def test_an_unknown_setting_is_an_error_with_the_known_ones_and_a_position() -> None:
    with pytest.raises(ExprError) as err:
        typed("amount <= settings.limt")
    assert "unknown setting 'limt'" in err.value.message and "limit" in err.value.message and err.value.pos == 10
    with pytest.raises(ExprError, match="none declared"):
        check_scoped("settings.limit", FIELDS, {})
    with pytest.raises(ExprError, match="cannot be used in this expression"):
        check_scoped("settings.limit", FIELDS, None)
    with pytest.raises(ExprError, match="expected a setting name"):
        typed("settings.")
    with pytest.raises(ExprError, match="expected a setting name"):
        typed("settings.1")


def test_settings_are_never_assignable_and_the_reserved_name_cannot_be_written_directly() -> None:
    for text in ("settings.limit = 5", "settings.limit := 5", "settings.limit += 1", "(settings.limit) = 1"):
        with pytest.raises(ExprError):
            typed(text)
    with pytest.raises(ExprError, match="reserved"):
        typed("_setting_limit > 1")
    with pytest.raises(ExprError, match="unknown field"):
        typed("settings > 1")  # `settings` alone is not a value
    # string literals are left alone
    assert typed("note == 'settings.limit'")["t"] == "bool"


def test_the_rewrite_keeps_every_position() -> None:
    src = "amount <= settings.limit and note == 'settings.x'"
    assert len(rewrite_settings(src, SETTINGS)) == len(src)


def test_the_python_evaluator_reads_the_value_it_is_given_and_fails_closed_without_one() -> None:
    guard = compile_python(canonical(typed("amount <= settings.limit")))
    assert guard({"amount": Decimal("5"), "_setting_limit": 10}) is True
    assert guard({"amount": Decimal("50"), "_setting_limit": 10}) is False  # a new value, a new answer
    assert guard({"amount": Decimal("5")}) is None  # no value -> null -> a guard is `is True`, so refused


def test_the_sql_emitter_refuses_settings_with_a_clear_message() -> None:
    with pytest.raises(ExprError, match="settings cannot be used in SQL expressions"):
        to_sql(typed("amount <= settings.limit"))
    assert "amount" in to_sql(typed("amount <= 5"))


def test_the_shared_judge_reports_settings_problems_like_any_other() -> None:
    ok = check_expression("amount <= settings.limit", FIELDS, settings=SETTINGS)
    assert ok.ok and ok.type == "bool"
    bad = check_expression("amount <= settings.nope", FIELDS, settings=SETTINGS)
    assert not bad.ok and bad.code == "invalid_expression" and "unknown setting 'nope'" in (bad.message or "")
    none = check_expression("amount <= settings.limit", FIELDS)  # a place that offers no settings
    assert not none.ok and "cannot be used" in (none.message or "")


# --- in a whole spec ------------------------------------------------------------------------------------

import copy  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from app.core.generator import generate  # noqa: E402
from app.core.spec_models import Spec  # noqa: E402
from app.core.validation import validate  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def spec_with(name: str, change: Any = None) -> Spec:
    data: dict[str, Any] = copy.deepcopy(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))
    if change is not None:
        change(data)
    return Spec.model_validate(data)


def test_guards_in_the_demo_specs_read_settings_and_validate() -> None:
    for name in ("demo_invoice", "demo_leave"):
        spec = spec_with(name)
        assert validate(spec) == []
        assert any("settings." in (t.when or "") for m in spec.state_machines for t in m.transitions)


def test_an_unknown_setting_in_a_guard_is_a_validation_issue_with_its_path() -> None:
    def bad(d: dict[str, Any]) -> None:
        d["state_machines"][0]["transitions"][1]["when"] = "amount <= settings.approval_limit"

    issues = validate(spec_with("demo_invoice", bad))
    assert [(i.path, i.code) for i in issues] == [("state_machines[0].transitions[1].when", "invalid_expression")]
    assert "unknown setting 'approval_limit'" in issues[0].message and "approval_threshold" in issues[0].message


def test_a_project_without_settings_cannot_use_them_in_a_guard() -> None:
    def bad(d: dict[str, Any]) -> None:
        d["settings"] = []
        d["history"] = []  # (the history section does not depend on settings)

    issues = [i for i in validate(spec_with("demo_invoice", bad)) if i.code == "invalid_expression"]
    assert issues and all("none declared" in i.message for i in issues)


def test_in_a_multi_tenant_project_the_guarded_entity_must_belong_to_a_tenant() -> None:
    assert validate(spec_with("numbering")) == []

    def bad(d: dict[str, Any]) -> None:
        d["auth"]["permissions"] = [p for p in d["auth"]["permissions"] if p["row_rule"] != "tenant"]

    found = {(i.path, i.code) for i in validate(spec_with("numbering", bad))}
    assert ("state_machines[0].transitions[0].when", "tenancy_required") in found


def test_only_projects_whose_guards_read_settings_get_the_settings_engine() -> None:
    with_settings = generate(spec_with("demo_invoice"))
    assert "prime_settings" in with_settings["app/state_machines/engine.py"]
    assert "tests/test_state_machine_settings.py" in with_settings
    assert "prime_settings" in with_settings["app/state_machines/hooks.py"]
    assert "prime_settings" in with_settings["app/state_machines/router.py"]

    def literal(d: dict[str, Any]) -> None:
        for t in d["state_machines"][0]["transitions"]:
            if t.get("when"):
                t["when"] = t["when"].replace("settings.approval_threshold", "10000")

    without = generate(spec_with("demo_invoice", literal))
    assert "prime_settings" not in without["app/state_machines/engine.py"]
    assert "tests/test_state_machine_settings.py" not in without
    assert "_setting_" not in without["app/state_machines/definitions.py"]
