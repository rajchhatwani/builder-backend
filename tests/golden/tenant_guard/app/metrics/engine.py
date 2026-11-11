"""Metrics engine (generated): the platform's deterministic rules, computed IN SQL.

A definition is DATA (aggregate + typed filters + one optional group-by). Every value is a bound parameter,
every column is looked up on the model by name from the spec: no text from a caller reaches the SQL.

Rules (the same as the builder's metrics layer, so a number never depends on who computed it):
  * sum / min / max are exact `numeric`; avg is sum / count rounded to 6 places, ROUND_HALF_EVEN.
  * A float column is read through its text form first (0.1 means 0.1), like the builder does.
  * Results other than counts are decimal STRINGS, trailing zeros dropped, never exponent notation.
  * count / count_distinct are integers; empty input: count, count_distinct and sum are 0, others None.
  * A null never matches ANY filter (not even `ne`), like SQL; a null is skipped by every aggregate.
  * Group-by output is sorted by key text, the null group last; `value` is the aggregate of all filtered rows.
"""

import datetime as _dt
import operator
import uuid
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from typing import Any

import sqlalchemy as sa

from app.core.errors import AppError
from app.crud._base import Repository

NUMERIC_TYPES = frozenset({"integer", "bigint", "float", "decimal"})
AVG_PLACES = Decimal("0.000001")
_OPS = {
    "eq": operator.eq,
    "ne": operator.ne,
    "gt": operator.gt,
    "gte": operator.ge,
    "lt": operator.lt,
    "lte": operator.le,
}


def fmt(d: Decimal) -> str:
    if d == 0:
        return "0"
    s = format(d, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def typed_value(value: Any, ftype: str) -> Any:
    """A filter literal in its comparable form (the spec was validated, so a misfit is a bug: refuse)."""
    try:
        if ftype in NUMERIC_TYPES:
            return Decimal(str(value).strip())
        if ftype == "boolean":
            if not isinstance(value, bool):
                raise ValueError("boolean")
            return value
        if ftype == "date":
            return _dt.date.fromisoformat(str(value).strip())
        if ftype == "datetime":
            moment = _dt.datetime.fromisoformat(str(value).strip())
            return moment if moment.tzinfo else moment.replace(tzinfo=_dt.UTC)
        if ftype == "uuid":
            return str(value)
    except (InvalidOperation, ValueError) as exc:
        raise AppError("metric_invalid", "the metric definition does not fit the field type", 500) from exc
    return str(value)


def _numeric(repo: Repository[Any], name: str, ftype: str) -> Any:
    col = repo._col(name)
    if ftype == "float":
        return sa.cast(sa.cast(col, sa.Text), sa.Numeric())
    return sa.cast(col, sa.Numeric())


def _column(repo: Repository[Any], name: str, ftype: str) -> Any:
    """The column in the form filters and groups compare it in (numbers as numeric, uuids as text)."""
    if ftype in NUMERIC_TYPES:
        return _numeric(repo, name, ftype)
    col = repo._col(name)
    return sa.cast(col, sa.Text) if ftype == "uuid" else col


def filter_conditions(repo: Repository[Any], d: dict[str, Any], types: dict[str, str]) -> list[Any]:
    conditions: list[Any] = []
    for flt in d["filter"]:
        ftype = types[flt["field"]]
        col = _column(repo, flt["field"], ftype)
        op = flt["op"]
        if op == "in":
            conditions.append(col.in_([typed_value(v, ftype) for v in flt["value"]]))
            continue
        want = typed_value(flt["value"], ftype)
        conditions.append(_OPS[op](col, want))
    return conditions


def _selects(repo: Repository[Any], d: dict[str, Any], types: dict[str, str]) -> list[Any]:
    agg, name = d["agg"], d["field"]
    if agg == "count":
        return [sa.func.count() if name is None else sa.func.count(repo._col(name))]
    assert name is not None
    if agg == "count_distinct":
        return [sa.func.count(sa.distinct(repo._col(name)))]
    number = _numeric(repo, name, types[name])
    if agg == "sum":
        return [sa.func.sum(number)]
    if agg == "avg":
        return [sa.func.sum(number), sa.func.count(number)]
    return [sa.func.min(number) if agg == "min" else sa.func.max(number)]


def _value(d: dict[str, Any], row: Any) -> int | str | None:
    agg = d["agg"]
    if agg in ("count", "count_distinct"):
        return int(row[0])
    if agg == "sum":
        return fmt(Decimal(0) if row[0] is None else Decimal(row[0]))
    if agg == "avg":
        if not row[1]:
            return None
        with localcontext() as ctx:
            ctx.prec = 80
            avg = (Decimal(row[0]) / Decimal(int(row[1]))).quantize(AVG_PLACES, rounding=ROUND_HALF_EVEN)
        return fmt(avg)
    return None if row[0] is None else fmt(Decimal(row[0]))


def group_key(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, Decimal)):
        return fmt(Decimal(str(value)))
    if isinstance(value, _dt.datetime):
        # The form the API prints (and the builder's metrics read): UTC with a trailing Z.
        if value.tzinfo is not None:
            return value.astimezone(_dt.UTC).isoformat().replace("+00:00", "Z")
        return value.isoformat()
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


MAX_DISTINCT_VALUES = 50_000
_TEXT_TYPES = frozenset({"string", "text", "enum"})


def distinct_key(value: Any) -> str:
    """What makes two values the same for count_distinct (the builder's rule): numbers by value
    ("7", "7.0" and " 07 " are one), anything else by its text. A boolean is never a number."""
    if isinstance(value, bool):
        return str(value)
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        return str(value)
    return fmt(number) if number.is_finite() else str(value)


async def _distinct_in_python(
    repo: Repository[Any], d: dict[str, Any], types: dict[str, str], where: list[Any]
) -> dict[str, Any]:
    """count_distinct over text: SQL cannot see that "7" and "7.0" are one value, so the distinct
    values (bounded, like the builder's 50k-row cap) are keyed here."""
    name = d["field"]
    col = repo._col(name)
    group_col = None if d["group_by"] is None else _column(repo, d["group_by"], types[d["group_by"]])
    wanted = [col] if group_col is None else [col, group_col]
    found = (
        await repo.session.execute(
            sa.select(*wanted)
            .select_from(repo.model)
            .where(*where, col.is_not(None))
            .distinct()
            .limit(MAX_DISTINCT_VALUES + 1)
        )
    ).all()
    if len(found) > MAX_DISTINCT_VALUES:
        raise AppError("metric_too_large", "too many distinct values to count", 422)
    out: dict[str, Any] = {"value": len({distinct_key(r[0]) for r in found})}
    if group_col is None:
        return out
    keys = (
        await repo.session.execute(sa.select(group_col).select_from(repo.model).where(*where).distinct())
    ).all()
    buckets: dict[str | None, set[str]] = {group_key(r[0]): set() for r in keys}
    for r in found:
        buckets.setdefault(group_key(r[1]), set()).add(distinct_key(r[0]))
    order = sorted(buckets, key=lambda k: (k is None, k or ""))
    out["groups"] = [{"key": k, "value": len(buckets[k])} for k in order]
    return out


async def compute(repo: Repository[Any], d: dict[str, Any], types: dict[str, str]) -> dict[str, Any]:
    """The metric over exactly the rows `repo` may list (`repo._alive()` = soft delete, owner / tenant scope)."""
    where = [*repo._alive(), *filter_conditions(repo, d, types)]
    if d["agg"] == "count_distinct" and types[d["field"]] in _TEXT_TYPES:
        return await _distinct_in_python(repo, d, types, where)
    selects = _selects(repo, d, types)
    overall = (await repo.session.execute(sa.select(*selects).select_from(repo.model).where(*where))).one()
    out: dict[str, Any] = {"value": _value(d, overall)}
    if d["group_by"] is None:
        return out
    group_col = _column(repo, d["group_by"], types[d["group_by"]])
    rows = (
        await repo.session.execute(
            sa.select(group_col, *selects).select_from(repo.model).where(*where).group_by(group_col)
        )
    ).all()
    buckets = {group_key(row[0]): _value(d, row[1:]) for row in rows}
    order = sorted(buckets, key=lambda k: (k is None, k or ""))
    out["groups"] = [{"key": k, "value": buckets[k]} for k in order]
    return out
