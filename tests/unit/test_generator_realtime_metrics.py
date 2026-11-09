"""Realtime stream and metrics in generated projects (CP-4F1 WP3): rendering, gating, validation, and parity of the
ported rules with the platform's own modules. Specs without the blocks render exactly as before."""

import ast
import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from app.core import realtime as platform_rt
from app.core.generator import generate
from app.core.metrics import MetricDef, _fmt, compute
from app.core.spec_models import Spec
from app.core.validation import validate

TESTS = Path(__file__).resolve().parent.parent
FIXTURES = TESTS / "fixtures" / "specs"


def _spec(name: str = "realtime_metrics") -> Spec:
    return Spec.model_validate(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))


def _load(source: str, name: str) -> ModuleType:
    module = ModuleType(name)
    exec(compile(source, name, "exec"), module.__dict__)  # noqa: S102
    return module


def test_realtime_and_metrics_files_are_rendered_and_wired() -> None:
    files = generate(_spec())
    for path in ("protocol", "models", "service", "hooks", "router", "prune"):
        ast.parse(files[f"app/realtime/{path}.py"])
    for path in ("engine", "definitions", "router"):
        ast.parse(files[f"app/metrics/{path}.py"])
    assert "rt_events" in files["alembic/versions/0022_realtime.py"]
    assert 'down_revision: str | None = "0021"' not in files["alembic/versions/0022_realtime.py"]  # chained by the engine
    main = files["app/main.py"]
    assert "include_router(_realtime_router)" in main and "include_router(_metrics_router)" in main
    assert "_realtime_hooks.attach(" in files["app/crud/expenses.py"]
    assert "app.realtime import models" in files["app/models/__init__.py"]
    assert "rt_events" in files["tests/conftest.py"]
    assert "## Realtime" in files["README.md"] and "## Metrics" in files["README.md"]
    assert "REALTIME_MAX_STREAMS_PER_USER" in files[".env.example"]


def test_events_hold_ids_only() -> None:
    files = generate(_spec())
    models, hooks, service = (files[f"app/realtime/{n}.py"] for n in ("models", "hooks", "service"))
    assert "record_id" in models and "payload" not in models and "data:" not in models
    assert "getattr(item, \"tenant_id\"" in hooks and "values" not in hooks.split("def publish")[1]
    assert 'data={"entity": row.entity, "record_id": str(row.record_id), "op": row.op}' in service
    assert "pg_advisory_xact_lock" in service  # ids are committed in id order


def test_the_metric_sql_uses_the_row_scope_and_bound_values() -> None:
    files = generate(_spec())
    engine, router = files["app/metrics/engine.py"], files["app/metrics/router.py"]
    assert "repo._alive()" in engine
    assert "_fx.hidden_read(" in router and "403" in router
    assert "_ACCESS_expenses" in router and '"list"' in router


def test_without_the_blocks_nothing_is_emitted() -> None:
    spec = _spec()
    spec.realtime = None
    spec.metrics_layer = None
    files = generate(spec)
    assert not any(p.startswith(("app/realtime/", "app/metrics/")) or "0022" in p for p in files)
    assert not any("realtime" in t.lower() and p.endswith(".py") for p, t in files.items() if p != "tests/conftest.py")
    spec = _spec()
    spec.realtime.enabled = False  # type: ignore[union-attr]
    spec.metrics_layer.definitions = []  # type: ignore[union-attr]
    assert not any(p.startswith(("app/realtime/", "app/metrics/")) for p in generate(spec))


def test_realtime_only_and_metrics_only_are_independent() -> None:
    spec = _spec()
    spec.metrics_layer = None
    files = generate(spec)
    assert "app/realtime/router.py" in files and "app/metrics/router.py" not in files
    spec = _spec()
    spec.realtime = None
    files = generate(spec)
    assert "app/metrics/router.py" in files and "app/realtime/router.py" not in files
    assert "rt_events" not in files["tests/conftest.py"]


def test_migration_joins_the_chain_as_the_last_revision() -> None:
    files = generate(_spec())
    migrations = {p: t for p, t in files.items() if p.startswith("alembic/versions/")}
    revisions = {}
    for text in migrations.values():
        rev = text.split('revision: str = "')[1].split('"')[0]
        down = text.split("down_revision: str | None = ")[1].splitlines()[0].strip('"')
        revisions[rev] = down
    assert [r for r in revisions if r not in revisions.values()] == ["0022"]  # exactly one head
    assert revisions["0022"] == "0005"  # the state machine revision is the previous enabled one here


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda s: setattr(s.authorization, "model", "abac"), "needs_rbac"),
        (lambda s: s.metrics_layer.definitions.append({"key": "expense_total", "label": "x", "entity": "Expense", "agg": "count"}), "duplicate_key"),
        (lambda s: s.metrics_layer.definitions.append({"key": "bad", "label": "x", "entity": "Expense", "agg": "sum", "field": "category"}), "invalid_metric"),
        (lambda s: s.metrics_layer.definitions.append({"key": "bad2", "label": "x", "entity": "Nope", "agg": "count"}), "invalid_metric"),
        (lambda s: s.entities[1].options.operations.remove("list"), "no_list_operation"),
    ],
)
def test_validation_refuses_bad_blocks(mutate, code: str) -> None:  # noqa: ANN001
    spec = _spec()
    mutate(spec)
    assert code in {i.code for i in validate(spec)}


def test_the_ported_protocol_behaves_like_the_platform_module() -> None:
    proto = _load(generate(_spec())["app/realtime/protocol.py"], "gen_protocol")
    for value in (None, "", "12", " 7 ", "-1", "1.5", "abc", "9" * 20, str(2**63 - 1), str(2**63), "١٢"):
        assert proto.parse_last_event_id(value) == platform_rt.parse_last_event_id(value), value
    for last, floor, head in ((0, 0, 0), (5, 3, 9), (2, 3, 9), (10, 3, 9), (9, 3, 9), (4, 4, 4)):
        assert proto.needs_resync(last, floor, head) == platform_rt.needs_resync(last, floor, head)
    at = datetime(2026, 1, 1, tzinfo=UTC)
    event = proto.Event("Expense", "Expense.created\nx", {"a": "line\nbreak"}, at, 7)
    theirs = platform_rt.Event("p", "Expense", "Expense.created\nx", {"a": "line\nbreak"}, at, 7)
    assert b"\n\n" not in proto.encode_event(event)[:-2] and proto.encode_event(event).startswith(b"id: 7\nevent: Expense.created x\n")
    assert proto.encode_comment("x\ny") == platform_rt.encode_comment("x\ny")
    assert json.loads(proto.encode_event(event).split(b"data: ")[1])["id"] == json.loads(platform_rt.encode_event(theirs).split(b"data: ")[1])["id"]
    clock = [0.0]
    ours, base = proto.ReconnectGuard(3, 60.0, lambda: clock[0]), platform_rt.ReconnectGuard(3, 60.0, lambda: clock[0])
    for t in (0, 1, 2, 3, 30, 61, 62, 63, 64):
        clock[0] = float(t)
        assert ours.check("k") == base.check("k"), t
    lim, plim = proto.ConnectionLimiter(2), platform_rt.ConnectionLimiter(2)
    for op in ("a", "a", "a", "b", "r", "a"):
        if op == "r":
            lim.release("a")
            plim.release("a")
        else:
            assert lim.acquire(op) == plim.acquire(op)


def test_the_ported_metric_rules_equal_the_platform_for_formatting() -> None:
    engine = _load(generate(_spec())["app/metrics/engine.py"].replace("from app.core.errors import AppError", "AppError = RuntimeError").replace("from app.crud._base import Repository", "Repository = dict"), "gen_engine")
    for text in ("0", "0.000", "12.50", "100", "1E+3", "-0.50", "3.141590", "1234567890.123456789"):
        value = Decimal(text)
        assert engine.fmt(value) == _fmt(value), text
    assert engine.group_key(True) == "true" and engine.group_key(Decimal("2.50")) == "2.5" and engine.group_key(None) is None
    row_sum = engine._value({"agg": "avg"}, (Decimal("10"), 3))
    assert row_sum == compute(MetricDef(key="k", label="l", entity="E", agg="avg", field="f"), [{"f": 3}, {"f": 3}, {"f": 4}]).value == "3.333333"
    assert engine._value({"agg": "avg"}, (Decimal("1"), 8)) == "0.125"
    assert engine._value({"agg": "avg"}, (Decimal("5"), 32)) == compute(MetricDef(key="k", label="l", entity="E", agg="avg", field="f"), [{"f": "0.15625"}] * 32).value
    assert engine._value({"agg": "sum"}, (None,)) == "0" and engine._value({"agg": "avg"}, (None, 0)) is None
    assert engine._value({"agg": "min"}, (None,)) is None and engine._value({"agg": "count"}, (4,)) == 4


def test_count_distinct_and_date_group_keys_match_the_platform() -> None:
    from datetime import date  # noqa: PLC0415

    from app.core.metrics import _distinct_key, _group_key  # noqa: PLC0415

    engine = _load(generate(_spec())["app/metrics/engine.py"].replace("from app.core.errors import AppError", "AppError = RuntimeError").replace("from app.crud._base import Repository", "Repository = dict"), "gen_engine2")
    for value in ("7", "7.0", " 07 ", "abc", "1e2", "100", "NaN", "inf", "", "007x", "2024-03-01", True, False, 3, 2.5):
        assert engine.distinct_key(value) == _distinct_key(value), value
    assert engine.distinct_key("7") == engine.distinct_key("7.0") == engine.distinct_key(" 07 ")
    assert engine.distinct_key("abc") != engine.distinct_key("7")
    # a date prints as the API prints it; a datetime in UTC ends in Z (what the builder reads from the API)
    assert engine.group_key(date(2024, 3, 1)) == _group_key("2024-03-01") == "2024-03-01"
    moment = datetime(2024, 3, 1, 10, 0, tzinfo=UTC)
    assert engine.group_key(moment) == _group_key("2024-03-01T10:00:00Z") == "2024-03-01T10:00:00Z"
    assert engine.group_key(datetime(2024, 3, 1, 12, 0, tzinfo=timezone(timedelta(hours=2)))) == "2024-03-01T10:00:00Z"


def test_realtime_announces_transitions_and_caps_streams_globally() -> None:
    files = generate(_spec())
    hooks = files["app/realtime/hooks.py"]
    assert '"transition": "updated"' in hooks
    proto = _load(files["app/realtime/protocol.py"], "gen_protocol2")
    limiter = proto.ConnectionLimiter(max_per_user=5, max_total=3)
    assert [limiter.acquire(u) for u in ("a", "b", "c")] == [True, True, True]
    assert limiter.at_capacity() and limiter.total() == 3
    limiter.release("b")
    assert not limiter.at_capacity() and limiter.acquire("d")
    assert proto.MAX_STREAMS_TOTAL == 50 and proto.STREAMS_AT_CAPACITY == "realtime_at_capacity"
    router = files["app/realtime/router.py"]
    assert "_limiter.at_capacity()" in router and "503" in router and "await session.close()" in router
    assert "idle * 1.5" in router
    assert "REALTIME_MAX_STREAMS=50" in files[".env.example"] and "REALTIME_MAX_STREAMS`" in files["README.md"]
