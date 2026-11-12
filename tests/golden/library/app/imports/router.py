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
from app.core.errors import AppError
from app.crud.authors import AuthorRepository
from app.crud.books import BookRepository
from app.crud.members import MemberRepository
from app.crud.profiles import ProfileRepository
from app.crud.shelves import ShelfRepository
from app.imports import csv_import as _ci
from app.imports import service as _service
from app.imports.fields import ENTITIES as _FIELDS
from app.schemas.authors import AuthorCreate
from app.schemas.books import BookCreate
from app.schemas.members import MemberCreate
from app.schemas.profiles import ProfileCreate
from app.schemas.shelves import ShelfCreate


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


@router.post("/authors/import", response_model=_service.ImportResult)
async def import_authors(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Author rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = AuthorRepository(session)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Author"],
        AuthorCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/authors/export.csv", response_class=_fa.Response)
async def export_authors(
    session: _db.SessionDep,
) -> _fa.Response:
    """Export Author as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = AuthorRepository(session)
    hidden = _EMPTY
    names = [n for n in ('id', 'name', 'bio', 'born_on', 'rating', 'created_at',) if n not in hidden]
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
    headers = {"Content-Disposition": 'attachment; filename="authors.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/books/import", response_model=_service.ImportResult)
async def import_books(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Book rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = BookRepository(session)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Book"],
        BookCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/books/export.csv", response_class=_fa.Response)
async def export_books(
    session: _db.SessionDep,
) -> _fa.Response:
    """Export Book as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = BookRepository(session)
    hidden = _EMPTY
    names = [n for n in ('id', 'title', 'isbn', 'pages', 'price', 'status', 'published_at', 'in_stock', 'extra', 'catalog_id', 'author_id', 'shelf_id', 'created_at',) if n not in hidden]
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
    headers = {"Content-Disposition": 'attachment; filename="books.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/members/import", response_model=_service.ImportResult)
async def import_members(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Member rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = MemberRepository(session)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Member"],
        MemberCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/members/export.csv", response_class=_fa.Response)
async def export_members(
    session: _db.SessionDep,
) -> _fa.Response:
    """Export Member as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = MemberRepository(session)
    hidden = _EMPTY
    names = [n for n in ('id', 'name', 'email', 'joined_on', 'sponsor_id', 'created_at',) if n not in hidden]
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
    headers = {"Content-Disposition": 'attachment; filename="members.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/profiles/import", response_model=_service.ImportResult)
async def import_profiles(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Profile rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = ProfileRepository(session)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Profile"],
        ProfileCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/profiles/export.csv", response_class=_fa.Response)
async def export_profiles(
    session: _db.SessionDep,
) -> _fa.Response:
    """Export Profile as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = ProfileRepository(session)
    hidden = _EMPTY
    names = [n for n in ('id', 'bio', 'member_id', 'created_at',) if n not in hidden]
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
    headers = {"Content-Disposition": 'attachment; filename="profiles.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/shelves/import", response_model=_service.ImportResult)
async def import_shelves(
    session: _db.SessionDep,
    file: _t.Annotated[_fa.UploadFile, _fa.File(description="A CSV file (UTF-8; comma, semicolon or tab separated)")],
    mapping: _t.Annotated[str | None, _fa.Form(description="JSON object: field name -> csv header")] = None,
    dry_run: _t.Annotated[bool, _fa.Query(description="Check the file, write nothing")] = False,
) -> _service.ImportResult:
    """Import Shelf rows from a CSV. Idempotent: rows already present (or repeated in the file) are
    counted as duplicates. All new rows are written in one transaction."""
    data = await _read_upload(file)
    repo = ShelfRepository(session)
    hidden_write = hidden_read = _EMPTY

    def payload(body: _t.Any) -> dict[str, _t.Any]:
        return body.model_dump()

    return await _service.run_import(
        repo,
        _FIELDS["Shelf"],
        ShelfCreate,
        data=data,
        mapping_raw=mapping,
        hidden_write=hidden_write,
        hidden_read=hidden_read,
        dry_run=dry_run,
        make_payload=payload,
    )


@router.get("/shelves/export.csv", response_class=_fa.Response)
async def export_shelves(
    session: _db.SessionDep,
) -> _fa.Response:
    """Export Shelf as CSV: readable fields only, at most 10000 rows (header X-Export-Truncated: true when cut)."""
    repo = ShelfRepository(session)
    hidden = _EMPTY
    names = [n for n in ('id', 'label', 'created_at',) if n not in hidden]
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
    headers = {"Content-Disposition": 'attachment; filename="shelves.csv"'}
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return _fa.Response(content=out.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)
