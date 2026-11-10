"""The import run (generated): parse, validate, field access, dedupe, insert in ONE transaction.

Per row: a field the caller may not write that carries a value is a row error (`field_not_writable`) and is
never written; the Create schema validates the rest. A row is a duplicate when its dedupe key (unique fields,
else the whole record of writable fields) matches a row already in the table (inside the caller's scope) or an
earlier row of the same file, so re-uploading a file creates nothing. Rows the caller may not read are never
echoed: a rejected row shows only columns that are not hidden fields.
"""

import datetime as dt
import decimal
import json
import uuid
from collections.abc import Callable
from typing import Any

import sqlalchemy as sa
from pydantic import BaseModel, ValidationError

from app.core.errors import AppError
from app.crud._base import Repository
from app.crud.lifecycle import run_stage
from app.imports import csv_import as ci

MAX_REJECTED_SHOWN = 100
MAX_EXISTING_ROWS = 200_000
_ECHO_CELL_CHARS = 200


class Counts(BaseModel):
    total: int
    created: int
    duplicate: int
    rejected: int


class RejectedRow(BaseModel):
    row: int
    errors: list[dict[str, str]]
    values: dict[str, str]


class ImportResult(BaseModel):
    dry_run: bool
    counts: Counts
    would_create: int
    rejected_rows: list[RejectedRow]
    rejected_truncated: bool = False


def _file_error(exc: ci.ImportDataError) -> AppError:
    return AppError(exc.code, exc.message, 413 if exc.code == "import_too_large" else 422)


def canon(value: Any) -> Any:
    """One comparable, JSON-safe form of a value, whether it came from a CSV cell or from the database."""
    if isinstance(value, decimal.Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, dt.datetime):
        return (value if value.tzinfo else value.replace(tzinfo=dt.UTC)).astimezone(dt.UTC).isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return float(value)
    return value


def _mapping(raw: str | None, parsed: ci.ParsedCsv, entity: ci.SpecEntity) -> dict[str, str]:
    if raw is None or not raw.strip():
        return ci.suggest_mapping(parsed.headers, entity)
    try:
        loaded = json.loads(raw)
    except ValueError as exc:
        raise AppError("import_bad_mapping", "mapping must be valid JSON", 422) from exc
    try:
        return ci.clean_mapping(loaded, parsed.headers, entity)
    except ci.ImportDataError as exc:
        raise _file_error(exc) from exc


def _blank(cell: str | None) -> bool:
    return cell is None or cell.strip() == ""


def _echo(row: dict[str, str], hidden_headers: set[str], hidden_norms: set[str]) -> dict[str, str]:
    return {
        h: v[:_ECHO_CELL_CHARS]
        for h, v in row.items()
        if h not in hidden_headers and ci._norm(h) not in hidden_norms
    }


def _schema_errors(exc: ValidationError) -> list[ci.FieldError]:
    out: list[ci.FieldError] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "row"
        out.append(ci.FieldError(loc, "invalid_value", str(err["msg"])[:200]))
    return out


async def _existing_keys(
    repo: Repository[Any], entity: ci.SpecEntity, writable: ci.SpecEntity
) -> set[str]:
    table = repo.model.__table__
    names = [f.name for f in writable.fields]
    conditions = repo._alive()
    if repo.owner_id is not None and "created_by_id" in table.c:
        conditions.append(table.c["created_by_id"] == repo.owner_id)
    if repo.tenant_id is not None and "tenant_id" in table.c:
        conditions.append(table.c["tenant_id"] == repo.tenant_id)
    stmt = sa.select(*[table.c[n] for n in names]).where(*conditions).limit(MAX_EXISTING_ROWS)
    keys: set[str] = set()
    for row in (await repo.session.execute(stmt)).all():
        record = {n: canon(v) for n, v in zip(names, row, strict=True)}
        keys.add(ci.dedupe_key(writable, record))
    return keys


async def run_import(
    repo: Repository[Any],
    entity: ci.SpecEntity,
    schema: type[BaseModel],
    *,
    data: bytes,
    mapping_raw: str | None,
    hidden_write: frozenset[str],
    hidden_read: frozenset[str],
    dry_run: bool,
    make_payload: Callable[[BaseModel], dict[str, Any]],
) -> ImportResult:
    try:
        parsed = ci.parse_csv(data)
    except ci.ImportDataError as exc:
        raise _file_error(exc) from exc
    mapping = _mapping(mapping_raw, parsed, entity)
    writable = ci.SpecEntity(entity.name, tuple(f for f in entity.fields if f.name not in hidden_write))
    writable_mapping = {k: v for k, v in mapping.items() if k not in hidden_write}
    hidden_headers = {mapping[k] for k in hidden_read if k in mapping}
    hidden_norms = {ci._norm(k) for k in hidden_read}

    seen = await _existing_keys(repo, entity, writable)
    duplicate = 0
    rejected: list[RejectedRow] = []
    rejected_count = 0
    pending: list[dict[str, Any]] = []

    def reject(row_no: int, raw: dict[str, str], errors: list[ci.FieldError]) -> None:
        nonlocal rejected_count
        rejected_count += 1
        if len(rejected) < MAX_REJECTED_SHOWN:
            rejected.append(
                RejectedRow(
                    row=row_no,
                    errors=[e.as_dict() for e in errors],
                    values=_echo(raw, hidden_headers, hidden_norms),
                )
            )

    for row_no, raw in enumerate(parsed.rows, start=1):
        errors = [
            ci.FieldError(name, "field_not_writable", "you may not set this field")
            for name in sorted(hidden_write)
            if name in mapping and not _blank(raw.get(mapping[name]))
        ]
        result = ci.validate_values(ci.values_from_raw(raw, writable_mapping), writable)
        errors.extend(result.errors)
        body: BaseModel | None = None
        if not errors and result.record is not None:
            try:
                body = schema.model_validate({k: v for k, v in result.record.items() if v is not None})
            except ValidationError as exc:
                errors = _schema_errors(exc)
        if errors or body is None:
            reject(row_no, raw, errors)
            continue
        values = make_payload(body)
        key = ci.dedupe_key(writable, {f.name: canon(values.get(f.name)) for f in writable.fields})
        if key in seen:
            duplicate += 1
            continue
        if not dry_run:
            try:
                values = await _prepare(repo, values)
            except AppError as exc:
                reject(row_no, raw, [ci.FieldError(_detail_field(exc), exc.code, exc.message[:200])])
                continue
        seen.add(key)
        pending.append(values)

    created = 0
    if not dry_run and pending:
        for values in pending:
            repo.session.add(repo.model(**values))
        await repo._flush()  # one transaction: a conflict (unique column) rolls everything back
        await repo._commit()
        created = len(pending)
    return ImportResult(
        dry_run=dry_run,
        counts=Counts(
            total=len(parsed.rows), created=created, duplicate=duplicate, rejected=rejected_count
        ),
        would_create=len(pending) if dry_run else 0,
        rejected_rows=rejected,
        rejected_truncated=rejected_count > len(rejected),
    )


def _detail_field(exc: AppError) -> str:
    details = getattr(exc, "details", None) or []
    return str(details[0].get("field", "row")) if details else "row"


async def _prepare(repo: Repository[Any], values: dict[str, Any]) -> dict[str, Any]:
    """The same steps as Repository.create up to the write (before_save hooks, owner / tenant stamp, policy,
    references), without its commit. after_save / after_commit hooks do not run for imported rows."""
    ctx = repo._ctx("create", dict(values))
    await run_stage("before_save", repo.hooks, ctx)
    out = ctx.values
    if repo.owner_id is not None:
        out["created_by_id"] = repo.owner_id
    if repo.tenant_id is not None:
        out["tenant_id"] = repo.tenant_id
    if repo.policy is not None:
        repo.policy.check_new_row(out)
    await repo._pop_related(out)
    await repo._check_references(out)
    return out
