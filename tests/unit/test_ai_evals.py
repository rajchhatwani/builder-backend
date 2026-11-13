"""CP-5E: the AI pack, evals block (D38 eval harness). Spec rules, emission only when declared, migration 0042, the generated
scoring executed on hand-computed cases. Running suites against a database and the require_eval gate are proven by
tests/e2e/test_ai_agents_stack.py (agents) and tests/e2e/test_ai_evals_stack.py (evals)."""

import ast
import json
from pathlib import Path
from typing import Any

from app.core.generator import generate
from app.core.spec_models import Spec
from app.core.validation import validate
from app.core.validation_ai import ai_tables

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "specs"


def _raw() -> dict[str, Any]:
    return json.loads((FIXTURES / "ai_agents_evals.json").read_text(encoding="utf-8"))


def _files(raw: dict[str, Any] | None = None) -> dict[str, str]:
    return generate(Spec.model_validate(raw or _raw()))


def test_the_suites_of_the_fixture_are_valid_and_cover_the_scoring_edges() -> None:
    raw = _raw()
    assert validate(Spec.model_validate(raw)) == []
    suites = {s["name"]: s for s in raw["packs"]["ai"]["evals"]["suites"]}
    assert set(suites) == {"guarded_basic", "drafter_mixed", "autopilot_strict"}
    assert suites["drafter_mixed"]["pass_bp"] == 5000 and len(suites["drafter_mixed"]["cases"]) == 2
    assert suites["guarded_basic"]["pass_bp"] == 10000
    assert next(a for a in raw["packs"]["ai"]["agents"]["agents"] if a["name"] == "guarded")["require_eval"] == "guarded_basic"


def test_eval_defaults() -> None:
    raw = _raw()
    for agent in raw["packs"]["ai"]["agents"]["agents"]:
        agent["require_eval"] = None
    raw["packs"]["ai"]["evals"] = {"suites": [{"name": "s", "agent": "watcher", "cases": [{"name": "c", "goal": "g", "expect_actions": ["add_note"]}]}]}
    spec = Spec.model_validate(raw)
    ev = spec.packs.ai.evals  # type: ignore[union-attr]
    assert ev is not None and ev.run_roles == ["admin"]
    assert (ev.suites[0].pass_bp, ev.suites[0].cases[0].forbid_actions) == (8000, [])
    assert validate(spec) == []


def test_the_evals_table_and_migration() -> None:
    spec = Spec.model_validate(_raw())
    assert ai_tables(spec)[-1] == "ai_eval_runs"
    files = _files()
    migration = files["alembic/versions/0042_ai_evals.py"]
    for needle in ("ai_eval_runs", "score_bp", "ck_ai_eval_runs_score", "ck_ai_eval_runs_counts", "JSONB", "ix_ai_eval_runs_suite_created_at", "tenant_id"):
        assert needle in migration, needle
    assert 'revision: str = "0042"' in migration and 'down_revision: str | None = "0041"' in migration
    assert "AiEvalRun" in files["app/ai/evals_models.py"]


def test_the_suites_reach_the_config_and_the_roles() -> None:
    files = _files()
    ns: dict[str, Any] = {}
    exec(compile(files["app/ai/evals_config.py"], "evals_config", "exec"), ns)  # noqa: S102
    assert ns["RUN_ROLES"] == ("admin",)
    suite = ns["SUITES"]["guarded_basic"]
    assert suite["agent"] == "guarded" and suite["pass_bp"] == 10000 and len(suite["cases"]) == 2
    assert suite["cases"][0]["expect_actions"] == ["add_note"] and "[[fake:json=" in suite["cases"][0]["goal"]
    router = files["app/ai/evals_router.py"]
    assert "/ai/evals" in router and "_agents.APPROVE_ROLES" in router


def test_every_evals_file_parses_and_runs_cases_only_through_the_agent_runtime() -> None:
    files = _files()
    for path in ("app/ai/evals_models.py", "app/ai/evals_schemas.py", "app/ai/evals_service.py", "app/ai/evals_router.py", "app/ai/evals_config.py"):
        ast.parse(files[path], filename=path)
    service = files["app/ai/evals_service.py"]
    assert "_agents.start_run(" in service and "dry=True" in service
    assert "_gateway.complete" not in service and "providers" not in service


def _score(passed: int, total: int, pass_bp: int) -> tuple[int, bool]:
    """The scoring rule of the generated run_suite, lifted from its source (hand-checked below)."""
    source = _files()["app/ai/evals_service.py"]
    assert "score = passed_count * 10_000 // total if total else 0" in source
    assert "passed=score >= _t.cast(int, suite[\"pass_bp\"])" in source
    score = passed * 10_000 // total if total else 0
    return score, score >= pass_bp


def test_scoring_is_integer_basis_points() -> None:
    assert _score(1, 3, 3333) == (3333, True)  # floor(10000 / 3), exactly at the threshold
    assert _score(1, 3, 3334) == (3333, False)
    assert _score(2, 3, 6667) == (6666, False)
    assert _score(1, 2, 5000) == (5000, True)
    assert _score(0, 4, 0) == (0, True)
    assert _score(4, 4, 10000) == (10000, True)
    assert isinstance(_score(7, 9, 1)[0], int)
