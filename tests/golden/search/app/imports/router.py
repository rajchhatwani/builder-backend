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
from fastapi.routing import APIRoute as _APIRoute

from app import db as _db
from app.auth import access as _access
from app.auth import field_access as _fx
from app.core.errors import AppError
from app.crud.tickets import TicketRepository
from app.imports import csv_import as _ci
from app.imports import service as _service
from app.imports.fields import ENTITIES as _FIELDS
from app.routers.tickets import _ACCESS as _ACCESS_tickets
from app.schemas.tickets import TicketCreate


class _BodyLimitRoute(_APIRoute):
    """Refuses an oversized upload BEFORE Starlette spools the multipart body to disk: a declared Content-Length
    over the cap is answered at once, and a body that streams more than the cap (chunked, or a lying header)
    is cut off while it is read. Answer: 413 import_too_large."""

    def get_route_handler(self) -> _t.Callable[[_fa.Request], _t.Coroutine[_t.Any, _t.Any, _fa.Response]]:
        original = super().get_route_handler()

        async def handler(request: _fa.Request) -> _fa.Response:
            declared = request.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > BODY_LIMIT:
                raise _too_large()
            seen = 0
            exceeded = False

            async def receive() -> _t.Any:
                nonlocal seen, exceeded
                message = await request.receive()
                seen += len(message.get("body", b""))
                if seen > BODY_LIMIT:
                    exceeded = True
                    raise _TooLarge
                return message

            try:
                return await original(_fa.Request(request.scope, receive))
            except Exception:
                if exceeded:
                    raise _too_large() from None
                raise

        return handler


router = _fa.APIRouter(tags=["import"], route_class=_BodyLimitRoute)
EXPORT_ROW_CAP = 10000
BODY_LIMIT = _ci.MAX_BYTES + 256 * 1024  # the file cap plus multipart framing and the mapping field


class _TooLarge(Exception):
    pass


def _too_large() -> AppError:
    return AppError("import_too_large", f"the file is larger than {_ci.MAX_BYTES} bytes", 413)
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


@router.post("/tickets/import", response_model=_service.ImportResult)
async def import_tickets(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_tickets["create"])],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Ticket rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = TicketRepository(session, **access.repo_kwargs)
    hidden_write = _fx.hidden_write("Ticket", access.user)
    hidden_read = _fx.hidden_read("Ticket", access.user)

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return _fx.payload("Ticket", access.user, body, "create")

    return await _service.run_import(
        repo,
        _FIELDS["Ticket"],
        TicketCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/tickets/export.csv", response_class=_fa.Response)
async def export_tickets(
    session: _db.SessionDep,
    access: _t.Annotated[_access.Access, _fa.Depends(_ACCESS_tickets["list"])],
) -> _fa.Response:
    """Export Ticket as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = TicketRepository(session, **access.repo_kwargs)
    hidden = _fx.hidden_read("Ticket", access.user)
    names = [n for n in ('id', 'title', 'internal_note', 'created_at',) if n not in hidden]
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
    headers = {"Content-Disposition": 'attachment; filename="tickets.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)
