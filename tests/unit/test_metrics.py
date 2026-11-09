"""B4-4: metrics core is pure, exact and deterministic."""

from typing import Any

import pytest

from app.core import metrics as mx
from app.core.spec_models import SpecEntity, SpecField

ENTITY = SpecEntity(
    name="Order",
    table_name="orders",
    plural_path="orders",
    fields=[
        SpecField(name="amount", type="decimal"),
        SpecField(name="qty", type="integer"),
        SpecField(name="ratio", type="float"),
        SpecField(name="status", type="string"),
        SpecField(name="paid", type="boolean"),
        SpecField(name="placed", type="date"),
        SpecField(name="blob", type="json"),
    ],
)


def d(**kw: Any) -> mx.MetricDef:
    base: dict[str, Any] = {"key": "m", "label": "M", "entity": "Order", "agg": "count"}
    return mx.parse_metric({**base, **kw})


def run(defn: mx.MetricDef, rows: list[dict[str, Any]]) -> dict[str, Any]:
    mx.validate_metric(defn, ENTITY)
    return mx.compute(defn, rows, ENTITY).as_dict()


def test_empty_dataset() -> None:
    assert run(d(), [])["value"] == 0
    assert run(d(agg="sum", field="amount"), [])["value"] == "0"
    assert run(d(agg="avg", field="amount"), [])["value"] is None
    assert run(d(agg="min", field="amount"), [])["value"] is None
    assert run(d(agg="max", field="amount"), [])["value"] is None
    assert run(d(agg="count_distinct", field="status"), [])["value"] == 0
    assert run(d(group_by="status"), [])["groups"] == []


def test_decimal_exactness() -> None:
    rows = [{"amount": "0.10"}, {"amount": "0.20"}, {"amount": 0.1}] * 1000
    assert run(d(agg="sum", field="amount"), rows)["value"] == "400"  # (0.1+0.2+0.1)*1000, exact
    assert run(d(agg="sum", field="amount"), [{"amount": "0.1"}, {"amount": "0.2"}])["value"] == "0.3"
    assert run(d(agg="avg", field="amount"), [{"amount": "1"}, {"amount": "2"}])["value"] == "1.5"
    assert run(d(agg="avg", field="amount"), [{"amount": "1"}, {"amount": "1"}, {"amount": "2"}])["value"] == "1.333333"
    assert run(d(agg="min", field="amount"), [{"amount": "2.50"}, {"amount": "10"}])["value"] == "2.5"
    assert run(d(agg="max", field="amount"), [{"amount": "2.50"}, {"amount": "10"}])["value"] == "10"
    assert run(d(agg="sum", field="amount"), [{"amount": "1E+2"}])["value"] == "100"  # never exponent form


def test_null_and_missing_values() -> None:
    rows = [{"amount": "5"}, {"amount": None}, {}, {"amount": "7"}]
    assert run(d(), rows)["value"] == 4
    assert run(d(field="amount"), rows)["value"] == 2
    assert run(d(agg="sum", field="amount"), rows)["value"] == "12"
    assert run(d(agg="avg", field="amount"), rows)["value"] == "6"
    # a null never matches a filter, not even ne
    ne = d(filter=[{"field": "status", "op": "ne", "value": "x"}])
    assert run(ne, [{"status": None}, {"status": "y"}, {}])["value"] == 1


def test_filters_are_typed() -> None:
    rows = [
        {"amount": "10.00", "qty": 1, "status": "open", "paid": True, "placed": "2026-01-05"},
        {"amount": "9.99", "qty": 5, "status": "closed", "paid": False, "placed": "2026-02-01"},
        {"amount": "100", "qty": 9, "status": "open", "paid": True, "placed": "2026-03-01"},
    ]
    f = lambda **k: run(d(filter=[k]), rows)["value"]  # noqa: E731
    assert f(field="amount", op="gt", value=10) == 1  # numeric, not text, comparison
    assert f(field="amount", op="eq", value="10") == 1  # 10.00 == 10
    assert f(field="amount", op="lte", value="10.00") == 2
    assert f(field="status", op="in", value=["open", "x"]) == 2
    assert f(field="paid", op="eq", value=True) == 2
    assert f(field="placed", op="gte", value="2026-02-01") == 2
    both = d(filter=[{"field": "status", "op": "eq", "value": "open"}, {"field": "qty", "op": "gt", "value": 1}])
    assert run(both, rows)["value"] == 1


def test_count_distinct_and_group_by() -> None:
    rows = [
        {"status": "a", "amount": "1"}, {"status": "b", "amount": "2.5"},
        {"status": "a", "amount": "3"}, {"status": None, "amount": "4"}, {"amount": "1"},
    ]  # fmt: skip
    assert run(d(agg="count_distinct", field="status"), rows)["value"] == 2
    out = run(d(agg="sum", field="amount", group_by="status"), rows)
    assert out["value"] == "11.5"
    assert out["groups"] == [
        {"key": "a", "value": "4"}, {"key": "b", "value": "2.5"}, {"key": None, "value": "5"},
    ]  # fmt: skip


def test_deterministic() -> None:
    rows = [{"amount": str(i / 7), "status": str(i % 3)} for i in range(1, 50)]
    defn = d(agg="avg", field="amount", group_by="status")
    assert run(defn, rows) == run(defn, list(reversed(rows)))


@pytest.mark.parametrize(
    "raw",
    [
        {"key": "Bad-Key"},  # not snake_case
        {"key": "1x"},
        {"agg": "median", "field": "amount"},
        {"agg": "sum"},  # field required
        {"agg": "sum", "field": "status"},  # not numeric
        {"agg": "avg", "field": "paid"},
        {"agg": "sum", "field": "nope"},
        {"agg": "count_distinct", "field": "blob"},
        {"entity": "Nope"},
        {"field": "nope"},
        {"group_by": "nope"},
        {"group_by": "blob"},
        {"filter": [{"field": "nope", "op": "eq", "value": 1}]},
        {"filter": [{"field": "amount", "op": "like", "value": "1"}]},
        {"filter": [{"field": "amount", "op": "eq", "value": "abc"}]},
        {"filter": [{"field": "amount", "op": "eq", "value": True}]},
        {"filter": [{"field": "status", "op": "gt", "value": "a"}]},  # text is not ordered
        {"filter": [{"field": "paid", "op": "eq", "value": "yes"}]},
        {"filter": [{"field": "placed", "op": "eq", "value": "not a date"}]},
        {"filter": [{"field": "status", "op": "in", "value": []}]},
        {"filter": [{"field": "status", "op": "in", "value": "a"}]},
        {"filter": [{"field": "blob", "op": "eq", "value": "x"}]},
        {"filter": [{"field": "status", "op": "eq", "value": {"a": 1}}]},
        {"filter": [{"field": "status", "op": "eq", "value": "x"}] * 11},
        {"sql": "select 1"},  # unknown member: no free-form anything
    ],
)
def test_bad_definitions(raw: dict[str, Any]) -> None:
    with pytest.raises(mx.MetricError):
        mx.validated({"key": "m", "label": "M", "entity": "Order", "agg": "count", **raw}, ENTITY)


def test_non_object_definition() -> None:
    with pytest.raises(mx.MetricError):
        mx.parse_metric(["x"])
