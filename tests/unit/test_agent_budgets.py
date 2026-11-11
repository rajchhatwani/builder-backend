"""B3-1: budgets, loop detection and repair tracking (pure)."""

from app.services.agent.budgets import (
    CEILINGS,
    DEFAULT_MAX_STEPS,
    Budgets,
    LoopDetector,
    RepairTracker,
    Verdict,
    canonical_input,
    check_limits,
)


def test_defaults_and_tolerant_parsing() -> None:
    b = Budgets()
    assert (b.max_steps, b.max_repairs) == (DEFAULT_MAX_STEPS, 3)
    assert DEFAULT_MAX_STEPS == 60
    assert Budgets.from_dict(None) == b
    junk = {"max_steps": -1, "max_cost_micro_usd": "9", "max_wall_seconds": True, "x": 1}
    assert Budgets.from_dict(junk) == b
    assert Budgets.from_dict({"max_steps": 5}).max_steps == 5
    assert Budgets.from_dict({"max_steps": 10**9}).max_steps == CEILINGS["max_steps"]
    assert Budgets.from_dict(b.as_dict()) == b


def test_limits_order_and_codes() -> None:
    b = Budgets(max_steps=3, max_cost_micro_usd=100, max_wall_seconds=10)
    assert check_limits(b, steps=2, cost_micro_usd=99, elapsed_seconds=9.9) is None
    s = check_limits(b, steps=3, cost_micro_usd=500, elapsed_seconds=99)
    assert s is not None and s.code == "budget_steps"
    s = check_limits(b, steps=1, cost_micro_usd=100, elapsed_seconds=99)
    assert s is not None and s.code == "budget_cost"
    s = check_limits(b, steps=1, cost_micro_usd=1, elapsed_seconds=10)
    assert s is not None and s.code == "budget_wall"


def test_canonical_input_ignores_key_order() -> None:
    assert canonical_input({"a": 1, "b": [1, 2]}) == canonical_input({"b": [1, 2], "a": 1})


def test_loop_same_call_same_result_reflects_then_stops() -> None:
    d = LoopDetector()
    assert d.observe("read", {"a": 1, "b": 2}, {"ok": True}) == Verdict.ok
    assert d.observe("read", {"b": 2, "a": 1}, {"ok": True}) == Verdict.reflect
    assert d.observe("read", {"a": 1, "b": 2}, {"ok": True}) == Verdict.stop


def test_loop_ignores_different_input_or_different_result() -> None:
    d = LoopDetector()
    for i in range(10):
        assert d.observe("read", {"i": i}, {"ok": True}) == Verdict.ok
    for i in range(10):
        assert d.observe("poll", {}, {"n": i}) == Verdict.ok
    assert d.observe("other", {"i": 1}, {"ok": True}) == Verdict.ok


def test_same_failure_signature_reflects_then_stops() -> None:
    r = RepairTracker()
    f = [("G1.type", "app/x.py:3")]
    assert r.observe(f) == Verdict.ok
    assert r.observe(f) == Verdict.reflect
    assert r.observe(f) == Verdict.stop


def test_different_locations_share_the_per_rule_repair_cap() -> None:
    r = RepairTracker(max_repairs=3)
    verdicts = [r.observe([("G2.lint", f"f{i}.py:1")]) for i in range(5)]
    assert verdicts[:4] == [Verdict.ok] * 4  # first failure + 3 repairs
    assert verdicts[4] == Verdict.stop


def test_other_rule_is_independent() -> None:
    r = RepairTracker()
    assert r.observe([("A", "x")]) == Verdict.ok
    assert r.observe([("B", "x")]) == Verdict.ok
    assert r.observe([("A", "x")]) == Verdict.reflect
    assert r.observe([("B", "y")]) == Verdict.ok
