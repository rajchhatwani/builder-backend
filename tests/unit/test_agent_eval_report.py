"""B3-11: report and comparison logic of the agent eval suite (no database)."""

import copy

import pytest

from app.services.agent_eval import report as rep
from app.services.agent_eval.runner import EvalError, _MISSING, check_spec, resolve


def res(tid: str = "t1", **kw: object) -> rep.TaskResult:
    base = dict(passed=True, state="applied", gate_pass_first_try=True, repairs_used=0, steps_used=6, tokens=1000, approvals=2)
    base.update(kw)
    return rep.TaskResult(task_id=tid, **base)  # type: ignore[arg-type]


def test_summary_and_markdown() -> None:
    r = rep.build_report([res("b"), res("a", passed=False, failures=["boom"], gate_pass_first_try=False)])
    assert r["summary"]["pass_rate"] == 0.5 and r["summary"]["tasks"] == 2
    assert list(r["tasks"]) == ["a", "b"]
    md = rep.markdown(r, ["a: something"])
    assert "| a | NO |" in md and "boom" in md and "- a: something" in md
    assert "none" in rep.markdown(r, [])
    assert rep.dumps(r) == rep.dumps(copy.deepcopy(r))  # deterministic


def test_compare_is_clean_for_equal_and_better_runs() -> None:
    base = rep.build_report([res()])
    assert rep.compare(base, base) == []
    better = rep.build_report([res(tokens=500, repairs_used=0)])
    assert rep.compare(better, base) == []


@pytest.mark.parametrize(
    ("change", "needle"),
    [
        ({"passed": False, "failures": ["x"]}, "fails now"),
        ({"repairs_used": 1}, "repairs up"),
        ({"steps_used": 7}, "steps up"),
        ({"approvals": 3}, "approvals up"),
        ({"tokens": 1200}, "tokens up"),
        ({"gate_pass_first_try": False}, "gates no longer"),
    ],
)
def test_compare_flags_regressions(change: dict[str, object], needle: str) -> None:
    base = rep.build_report([res()])
    cur = rep.build_report([res(**change)])
    assert any(needle in x for x in rep.compare(cur, base))


def test_tolerance_and_missing_task() -> None:
    base = rep.build_report([res()])
    assert rep.compare(rep.build_report([res(tokens=1090)]), base) == []  # within 10 percent
    assert rep.compare(rep.build_report([res(repairs_used=1)]), base, {"repairs": 1}) == []
    assert any("missing" in x for x in rep.compare(rep.build_report([res("other")]), base))
    assert any("pass rate down" in x for x in rep.compare(rep.build_report([res(passed=False)]), base))


def test_spec_path_checks() -> None:
    spec = {"entities": [{"name": "A", "fields": [{"name": "x", "min_value": 0}]}], "hooks": []}
    assert resolve(spec, "entities[name=A].fields[name=x].min_value") == 0
    assert resolve(spec, "entities[name=B].name") is _MISSING
    ok = [{"path": "entities[name=A].name", "equals": "A"}, {"path": "entities[name=A].fields[name=y]", "absent": True}]
    assert check_spec(spec, ok) == []
    assert len(check_spec(spec, [{"path": "entities[name=A].name", "equals": "Z"}, {"path": "hooks[name=h].name"}])) == 2
    with pytest.raises(EvalError):
        resolve(spec, "entities[bad")
