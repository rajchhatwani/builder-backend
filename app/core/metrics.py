"""Metrics layer core (B4-4, C22): one named definition, computed the same way for every consumer.

Pure: no database, no clock, no network. A definition is DATA (aggregate + typed filters + one
optional group-by); there is no expression language and no SQL anywhere.

Rules (deterministic, so two reports over one definition always agree):
  * Sums, averages, minimums and maximums are computed with `Decimal`, never float arithmetic.
    A float field value is converted through `str()` first, so 0.1 means 0.1.
  * Results other than counts are returned as decimal STRINGS (JSON numbers would lose exactness).
    `sum`, `min`, `max` are exact; `avg` is rounded to 6 decimal places, ROUND_HALF_EVEN. Trailing
    zeros are dropped ("12.50" -> "12.5", "0.000" -> "0"); never exponent notation.
  * `count` and `count_distinct` are integers. `count` counts the filtered records (or, when a
    field is given, the records where that field is not null).
  * Empty input: count/count_distinct/sum are 0; avg/min/max are None (no value to report).
  * A null or missing field value is skipped by sum/avg/min/max/count_distinct. A null never
    matches ANY filter (not even `ne`), like SQL.
  * Group-by is capped at MAX_GROUPS distinct groups; beyond it `TooManyGroups` (never truncated).
  * Group-by output is a list sorted by group key (text order), the null group last; each group's
    key is the value as text (None for null/missing).
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.spec_models import SpecEntity

AGGS = ("count", "sum", "avg", "min", "max", "count_distinct")
OPS = ("eq", "ne", "gt", "gte", "lt", "lte", "in")
NUMERIC_TYPES = frozenset({"integer", "bigint", "float", "decimal"})
ORDERED_TYPES = NUMERIC_TYPES | {"date", "datetime"}
SCALAR_TYPES = ORDERED_TYPES | {"string", "text", "boolean", "uuid", "enum"}
MAX_FILTERS = 10
MAX_IN_VALUES = 100
MAX_GROUPS = 100  # distinct group-by values one metric may return
AVG_PLACES = Decimal("0.000001")
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,59}$")


class MetricError(ValueError):
    """The definition is not acceptable; the API renders it as `metric_invalid`."""

    code = "metric_invalid"


class TooManyGroups(MetricError):
    """The group-by produced more than MAX_GROUPS groups; refused, never silently truncated."""

    code = "metric_too_many_groups"


class MetricFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=120)
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte", "in"]
    value: Any


class MetricDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str = Field(min_length=1, max_length=120)
    entity: str = Field(min_length=1, max_length=120)
    agg: Literal["count", "sum", "avg", "min", "max", "count_distinct"]
    field: str | None = Field(default=None, max_length=120)
    filter: list[MetricFilter] = Field(default_factory=list, max_length=MAX_FILTERS)
    group_by: str | None = Field(default=None, max_length=120)
    unit: str | None = Field(default=None, max_length=30)

    @field_validator("key")
    @classmethod
    def _key(cls, v: str) -> str:
        if not _KEY_RE.fullmatch(v):
            raise ValueError("key must be snake_case: a-z, 0-9, _, starting with a letter, max 60")
        return v


def parse_metric(raw: object) -> MetricDef:
    """Definition JSON -> MetricDef, or MetricError (never a pydantic error)."""
    if not isinstance(raw, dict):
        raise MetricError("a metric definition is an object")
    try:
        return MetricDef.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "definition"
        raise MetricError(f"{where}: {first['msg']}") from None


def _field_types(entity: SpecEntity) -> dict[str, str]:
    return {f.name: f.type for f in entity.fields}


def _typed_value(value: Any, ftype: str, where: str) -> Any:
    """A filter literal in its comparable form; MetricError when it does not fit the field type."""
    if isinstance(value, (dict, list)) or value is None:
        raise MetricError(f"{where}: a filter value is a single text, number or boolean")
    try:
        if ftype in NUMERIC_TYPES:
            if isinstance(value, bool):
                raise MetricError(f"{where}: expected a number")
            d = Decimal(str(value).strip())
            if not d.is_finite():
                raise MetricError(f"{where}: expected a finite number")
            return d
        if ftype == "boolean":
            if not isinstance(value, bool):
                raise MetricError(f"{where}: expected true or false")
            return value
        if ftype == "date":
            return date.fromisoformat(str(value).strip())
        if ftype == "datetime":
            dt = datetime.fromisoformat(str(value).strip())
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (InvalidOperation, ValueError) as exc:
        if isinstance(exc, MetricError):
            raise
        raise MetricError(f"{where}: {value!r} does not fit a {ftype} field") from None
    if isinstance(value, bool) or not isinstance(value, str):
        raise MetricError(f"{where}: expected text")
    return value


def validate_metric(d: MetricDef, entity: SpecEntity | None) -> None:
    """Check the definition against the entity's spec; raises MetricError."""
    if entity is None or entity.name != d.entity:
        raise MetricError(f"entity: the project has no entity {d.entity!r}")
    types = _field_types(entity)
    if d.agg == "count":
        if d.field is not None and d.field not in types:
            raise MetricError(f"field: {d.field!r} is not a field of {d.entity}")
    else:
        if d.field is None:
            raise MetricError(f"field: agg {d.agg} needs a field")
        ftype = types.get(d.field)
        if ftype is None:
            raise MetricError(f"field: {d.field!r} is not a field of {d.entity}")
        if d.agg in ("sum", "avg", "min", "max") and ftype not in NUMERIC_TYPES:
            raise MetricError(f"field: {d.agg} needs a numeric field, {d.field!r} is {ftype}")
        if d.agg == "count_distinct" and ftype not in SCALAR_TYPES:
            raise MetricError(f"field: {d.field!r} ({ftype}) cannot be counted distinct")
    for i, flt in enumerate(d.filter):
        where = f"filter[{i}]"
        ftype = types.get(flt.field)
        if ftype is None:
            raise MetricError(f"{where}.field: {flt.field!r} is not a field of {d.entity}")
        if ftype not in SCALAR_TYPES:
            raise MetricError(f"{where}.field: {flt.field!r} ({ftype}) cannot be filtered")
        if flt.op in ("gt", "gte", "lt", "lte") and ftype not in ORDERED_TYPES:
            raise MetricError(f"{where}.op: {flt.op} needs a number, date or datetime field")
        if flt.op == "in":
            if not isinstance(flt.value, list) or not 1 <= len(flt.value) <= MAX_IN_VALUES:
                raise MetricError(f"{where}.value: `in` needs a list of 1 to {MAX_IN_VALUES} values")
            for v in flt.value:
                _typed_value(v, ftype, f"{where}.value")
        else:
            _typed_value(flt.value, ftype, f"{where}.value")
    if d.group_by is not None:
        gtype = types.get(d.group_by)
        if gtype is None:
            raise MetricError(f"group_by: {d.group_by!r} is not a field of {d.entity}")
        if gtype not in SCALAR_TYPES:
            raise MetricError(f"group_by: {d.group_by!r} ({gtype}) cannot be grouped")


def validated(raw: object, entity: SpecEntity | None) -> MetricDef:
    d = parse_metric(raw)
    validate_metric(d, entity)
    return d


# -- compute ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricResult:
    value: int | str | None
    groups: list[dict[str, Any]] | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"value": self.value}
        if self.groups is not None:
            out["groups"] = self.groups
        return out


def _num(v: Any) -> Decimal | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        d = Decimal(str(v).strip())
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _fmt(d: Decimal) -> str:
    if d == 0:
        return "0"
    s = format(d, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def _comparable(v: Any, ftype: str) -> Any:
    """The record's value in the same form as `_typed_value`, or None when absent/unusable."""
    if v is None:
        return None
    try:
        if ftype in NUMERIC_TYPES:
            return _num(v)
        if ftype == "date":
            return date.fromisoformat(str(v)[:10])
        if ftype == "datetime":
            dt = datetime.fromisoformat(str(v))
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return None
    return v


def _matches(value: Any, op: str, want: Any) -> bool:
    if value is None:
        return False
    if op == "eq":
        return bool(value == want)
    if op == "ne":
        return bool(value != want)
    if op == "in":
        return value in want
    if op == "gt":
        return bool(value > want)
    if op == "gte":
        return bool(value >= want)
    if op == "lt":
        return bool(value < want)
    return bool(value <= want)  # lte


def _aggregate(d: MetricDef, rows: list[dict[str, Any]]) -> int | str | None:
    if d.agg == "count":
        if d.field is None:
            return len(rows)
        return sum(1 for r in rows if r.get(d.field) is not None)
    assert d.field is not None
    if d.agg == "count_distinct":
        seen = {_distinct_key(r.get(d.field)) for r in rows if r.get(d.field) is not None}
        return len(seen)
    nums = [n for n in (_num(r.get(d.field)) for r in rows) if n is not None]
    if d.agg == "sum":
        with localcontext() as ctx:
            ctx.prec = 80
            return _fmt(sum(nums, Decimal(0)))
    if not nums:
        return None
    if d.agg == "min":
        return _fmt(min(nums))
    if d.agg == "max":
        return _fmt(max(nums))
    with localcontext() as ctx:
        ctx.prec = 80  # wide enough for the 50k-row cap of 38-digit numbers
        avg = (sum(nums, Decimal(0)) / Decimal(len(nums))).quantize(AVG_PLACES, rounding=ROUND_HALF_EVEN)
    return _fmt(avg)


def _distinct_key(v: Any) -> Any:
    n = _num(v)
    return _fmt(n) if n is not None else str(v)


def _group_key(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    n = _num(v) if isinstance(v, (int, float)) else None
    return _fmt(n) if n is not None else str(v)


def compute(d: MetricDef, records: list[dict[str, Any]], entity: SpecEntity | None = None) -> MetricResult:
    """The metric over `records` (each the `data` dict of one record of d.entity).

    Pass the entity spec so filters compare in the field's type (Decimal, date, ...). Without it
    every filter value is compared as given (use only for definitions already validated)."""
    types = _field_types(entity) if entity is not None else {}
    prepared: list[tuple[str, str, Any]] = []
    for flt in d.filter:
        ftype = types.get(flt.field, "string")
        if flt.op == "in":
            want: Any = [_typed_value(v, ftype, "filter") for v in flt.value]
        else:
            want = _typed_value(flt.value, ftype, "filter")
        prepared.append((flt.field, flt.op, (ftype, want)))
    rows = [
        r
        for r in records
        if all(
            _matches(_comparable(r.get(f), spec[0]), op, spec[1]) for f, op, spec in prepared
        )
    ]
    if d.group_by is None:
        return MetricResult(_aggregate(d, rows))
    buckets: dict[str | None, list[dict[str, Any]]] = {}
    for r in rows:
        buckets.setdefault(_group_key(r.get(d.group_by)), []).append(r)
    if len(buckets) > MAX_GROUPS:
        raise TooManyGroups(
            f"group_by: {d.group_by!r} has more than {MAX_GROUPS} distinct values; group by a coarser field"
        )
    order = sorted(buckets, key=lambda k: (k is None, k or ""))
    return MetricResult(
        _aggregate(d, rows),
        [{"key": k, "value": _aggregate(d, buckets[k])} for k in order],
    )
