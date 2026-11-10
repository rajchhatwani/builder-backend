"""Import / export routes (generated).

POST /<entity>/import      multipart `file` (+ optional `mapping` JSON: field -> csv header, `?dry_run=true`).
GET  /<entity>/export.csv  the readable fields of the rows the caller may list.

Import has the same caller access as the entity's create operation, export the same as its list operation (roles,
tenant, owner / row scope, policy). Fields the caller may not write are refused per row; fields the caller may not
read are not exported and not echoed. Text cells of an export are neutralized against spreadsheet formulas."""

import csv
import datetime as dt
import decimal
import io
import json
import typing as _t

import fastapi as _fa
import sqlalchemy as sa

from app import db as _db
from app.auth import access as _access
from app.auth import field_access as _fx
from app.core.errors import AppError
from app.crud.expenses import ExpenseRepository
from app.crud.payrolls import PayrollRepository
from app.imports import csv_import as _ci
from app.imports import service as _service
from app.imports.fields import ENTITIES as _FIELDS
from app.routers.expenses import _ACCESS as _ACCESS_expenses
from app.routers.payrolls import _ACCESS as _ACCESS_payrolls
from app.schemas.expenses import ExpenseCreate
from app.schemas.payrolls import PayrollCreate

router = _fa.APIRouter(tags=["import"])
EXPORT_ROW_CAP = 10000
_EMPTY = frozenset[str]()


def _cell(value: object) -> object:
    """A CSV cell: text goes through neutralize_formula (see app/imports/csv_import.py); numbers stay numbers."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    if isinstance(value, int | float | decimal.Decimal):
        return str(value)
    if isinstance(value, dict | list):
        return _ci.neutralize_formula(json.dumps(value, ensure_ascii=False))
    return _ci.neutralize_formula(str(value))


async def _read_upload(file: _fa.UploadFile) -> bytes:
    data = await file.read(_ci.MAX_BYTES + 1)
    if len(data) > _ci.MAX_BYTES:
        raise AppError("import_too_large", f"the file is larger than {_ci.MAX_BYTES} bytes", 413)
    return data


@router.post("/expenses/import", response_model=_service.ImportResult)
async def import_expenses(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_expenses["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Expense rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = ExpenseRepository(session, **access.repo_kwargs)
    hidden_write = _fx.hidden_write("Expense", access.user)
    hidden_read = _fx.hidden_read("Expense", access.user)

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return _fx.payload("Expense", access.user, body, "create")

    return await _service.run_import(
        repo,
        _FIELDS["Expense"],
        ExpenseCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/expenses/export.csv", response_class=_fa.Response)
async def export_expenses(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_expenses["list"])],
) -> _fa.Response:
    """Export Expense as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = ExpenseRepository(session, **access.repo_kwargs)
    hidden = _fx.hidden_read("Expense", access.user)
    names = [n for n in ('id', 'category', 'amount', 'qty', 'rate', 'paid', 'cost_basis', 'spent_on', 'logged_at', 'code', 'status', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="expenses.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/payrolls/import", response_model=_service.ImportResult)
async def import_payrolls(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_payrolls["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Payroll rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = PayrollRepository(session, **access.repo_kwargs)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Payroll"],
        PayrollCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/payrolls/export.csv", response_class=_fa.Response)
async def export_payrolls(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_payrolls["list"])],
) -> _fa.Response:
    """Export Payroll as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = PayrollRepository(session, **access.repo_kwargs)
    hidden = _EMPTY
    names = [n for n in ('id', 'person', 'salary', 'created_at',) if n not in hidden]
    columns = [repo._col(n) for n in names]
    stmt = (
        sa.select(*columns)
        .where(*repo._alive())
        .order_by(repo._col("created_at"), repo._col("id"))
        .limit(EXPORT_ROW_CAP + 1)
    )
    rows = (await session.execute(stmt)).all()
    truncated = len(rows) > EXPORT_ROW_CAP
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(names)
    for row in rows[:EXPORT_ROW_CAP]:
        writer.writerow([_cell(v) for v in row])
    headers = {"Content-Disposition": 'attachment; filename="payrolls.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)
