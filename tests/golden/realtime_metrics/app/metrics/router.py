"""Metrics routes (generated): GET /metrics lists the definitions, GET /metrics/{key} computes one value.

The definitions are data in app/metrics/definitions.py (from the spec). A caller may read a metric only when
they may `list` its entity, and the value is computed over exactly the rows their list would return (soft
delete, owner / tenant scope), never over rows they cannot see. A metric that reads a field the caller may
not read (the field, the group-by or a filter) is refused with 403: it would reveal that field."""

import typing as _t

import fastapi as _fa

from app import db as _db
from app.auth import field_access as _fx
from app.auth.deps import CurrentUser
from app.core.errors import AppError
from app.crud.expenses import ExpenseRepository
from app.crud.payrolls import PayrollRepository
from app.metrics import engine as _engine
from app.metrics.definitions import FIELD_TYPES, METRICS
from app.routers.expenses import _ACCESS as _ACCESS_expenses
from app.routers.payrolls import _ACCESS as _ACCESS_payrolls

router = _fa.APIRouter(tags=["metrics"])

_REPOS: dict[str, _t.Any] = {
    "Expense": ExpenseRepository,
    "Payroll": PayrollRepository,
}


async def _repo_kwargs(entity: str, user: _t.Any) -> dict[str, _t.Any]:
    """The row scope of the caller's `list` on this entity (403 when their roles do not allow it)."""
    if entity == "Expense":
        return dict((await _ACCESS_expenses["list"](user)).repo_kwargs)
    if entity == "Payroll":
        return dict((await _ACCESS_payrolls["list"](user)).repo_kwargs)
    return {}  # a public list: no scope


def _used_fields(d: dict[str, _t.Any]) -> set[str]:
    used = {f["field"] for f in d["filter"]}
    used.update(n for n in (d["field"], d["group_by"]) if n is not None)
    return used


def _hidden(d: dict[str, _t.Any], user: _t.Any) -> set[str]:
    return _used_fields(d) & _fx.hidden_read(d["entity"], user)


def _public(d: dict[str, _t.Any]) -> dict[str, _t.Any]:
    return {k: d[k] for k in ("key", "label", "entity", "agg", "field", "filter", "group_by", "unit")}


@router.get("/metrics")
async def list_metrics(
    user: CurrentUser,
) -> list[dict[str, _t.Any]]:
    """The metrics this caller may read (entity listable by them, no field hidden from them)."""
    out: list[dict[str, _t.Any]] = []
    for d in METRICS.values():
        try:
            await _repo_kwargs(d["entity"], user)
        except AppError:
            continue
        if not _hidden(d, user):
            out.append(_public(d))
    return out


@router.get("/metrics/{key}")
async def get_metric(
    key: str,
    session: _db.SessionDep,
    user: CurrentUser,
) -> dict[str, _t.Any]:
    d = METRICS.get(key)
    if d is None:
        raise AppError("not_found", f"metric {key!r} not found", 404)
    kwargs = await _repo_kwargs(d["entity"], user)
    if _hidden(d, user):
        raise AppError("forbidden", "you do not have permission to read a field this metric uses", 403)
    repo = _REPOS[d["entity"]](session, **kwargs)
    result = await _engine.compute(repo, d, FIELD_TYPES[d["entity"]])
    return {"key": d["key"], "label": d["label"], "unit": d["unit"], **result}
