"""The import run (generated): parse, validate, field access, dedupe, insert in ONE transaction.

Per row: a field the caller may not write that carries a value is a row error (`field_not_writable`) and is
never written; the Create schema validates the rest. A row is a duplicate when its dedupe key (unique fields,
else the whole record of writable fields) matches a row already in the table (inside the caller's scope) or an
earlier row of the same file, so re-uploading a file creates nothing. The table is never scanned whole: the
candidate keys of the file are looked up with bounded IN queries per chunk (a cap that would be hit refuses the
file with a 422, never a silent partial check). Rows the caller may not read are never echoed: a rejected row
shows only columns that are not hidden fields, and a key that includes a field the caller may not read is
never answered with "duplicate" (generic `import_row_rejected` instead), so dedupe is no existence oracle.

Every created row runs the same lifecycle as Repository.create: before_save and the checks per row, after_save
inside the one transaction (an error rolls the whole import back), after_commit once the data is safe.
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
from app.crud.lifecycle import HookContext, run_stage
from app.imports import csv_import as ci

MAX_REJECTED_SHOWN = 100
PROBE_CHUNK = 500  # candidate keys per IN query
MAX_PROBE_ROWS = 50_000  # rows one probe may return; more means the file is refused (422), never truncated
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


def _scope(repo: Repository[Any]) -> list[Any]:
    table = repo.model.__table__
    conditions = repo._alive()
    if repo.owner_id is not None and "created_by_id" in table.c:
        conditions.append(table.c["created_by_id"] == repo.owner_id)
    if repo.tenant_id is not None and "tenant_id" in table.c:
        conditions.append(table.c["tenant_id"] == repo.tenant_id)
    return conditions


async def _probe(
    repo: Repository[Any],
    keys: ci.DedupeKeys,
    candidates: list[tuple[dict[str, Any], tuple[str, str]]],
) -> set[tuple[str, str]]:
    """Which of the candidate keys already exist in the caller's scope: bounded IN queries per chunk, grouped
    by the columns the key is built from. Scoped by tenant / owner / alive like every other read."""
    table = repo.model.__table__
    names = [f.name for f in keys.writable.fields]
    scope = _scope(repo)
    found: set[tuple[str, str]] = set()
    wanted = {key for _, key in candidates}
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for record, _key in candidates:
        groups.setdefault(keys.probe_names(record), []).append(record)
    for probe, records in groups.items():
        for i in range(0, len(records), PROBE_CHUNK):
            chunk = records[i : i + PROBE_CHUNK]
            stmt = sa.select(*[table.c[n] for n in names]).where(*scope)
            if probe:
                if len(probe) == 1:
                    stmt = stmt.where(table.c[probe[0]].in_([r[probe[0]] for r in chunk]))
                else:
                    stmt = stmt.where(
                        sa.tuple_(*[table.c[n] for n in probe]).in_(
                            [tuple(r[n] for n in probe) for r in chunk]
                        )
                    )
            else:  # only JSON columns carry the key: no equality in SQL, so a bounded ordered scan
                stmt = stmt.order_by(table.c["id"])
            rows = (await repo.session.execute(stmt.limit(MAX_PROBE_ROWS + 1))).all()
            if len(rows) > MAX_PROBE_ROWS:
                raise AppError(
                    "import_dedupe_too_large",
                    "too many existing rows match this file to check for duplicates; narrow the file",
                    422,
                )
            for row in rows:
                record = {n: canon(v) for n, v in zip(names, row, strict=True)}
                key = keys.of(record)
                if key in wanted:
                    found.add(key)
    return found


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

    keys = ci.DedupeKeys(writable, hidden_read)
    duplicate = 0
    rejected: list[RejectedRow] = []
    rejected_count = 0

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

    # pass 1: validate every row (schema, field access) and work out its dedupe key
    candidates: list[tuple[int, dict[str, str], dict[str, Any], tuple[str, str]]] = []
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
        key = keys.of({f.name: canon(values.get(f.name)) for f in writable.fields})
        candidates.append((row_no, raw, values, key))

    # pass 2: which keys exist already (bounded lookups), then dedupe, checks and hooks per row
    existing = await _probe(repo, keys, [(values, key) for _, _, values, key in candidates])
    seen: set[tuple[str, str]] = set()
    pending: list[tuple[dict[str, Any], HookContext]] = []
    for row_no, raw, values, key in candidates:
        if key in existing or key in seen:
            if key[0] == "guarded":  # a key over a field the caller may not read: no "duplicate" answer
                reject(row_no, raw, [ci.FieldError("row", "import_row_rejected", "this row could not be imported")])
            else:
                duplicate += 1
            continue
        try:  # also in a dry run, so would_create counts only rows the real import would accept
            prepared, ctx = await _prepare(repo, values)
        except AppError as exc:
            reject(row_no, raw, [ci.FieldError(_detail_field(exc), exc.code, exc.message[:200])])
            continue
        seen.add(key)
        pending.append((prepared, ctx))

    created = 0
    if not dry_run and pending:
        for prepared, ctx in pending:
            item = repo.model(**prepared)
            repo.session.add(item)
            ctx.item = item
        await repo._flush()  # one transaction: a conflict (unique column) rolls everything back
        try:
            for _, ctx in pending:
                await run_stage("after_save", repo.hooks, ctx)  # inside the transaction, like Repository.create
        except Exception:
            await repo.session.rollback()
            raise
        for _, ctx in pending:
            ctx.trace.append("commit")
        await repo._commit()
        for _, ctx in pending:
            await run_stage("after_commit", repo.hooks, ctx, fail_closed=False)
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


async def _prepare(repo: Repository[Any], values: dict[str, Any]) -> tuple[dict[str, Any], HookContext]:
    """The same steps as Repository.create up to the write (before_save hooks, owner / tenant stamp, policy,
    references), without its flush / commit. Returns the values to write and the hook context, which the
    caller later runs through after_save / after_commit. Writes nothing, so a dry run may call it."""
    ctx = repo._ctx("create", dict(values))
    await run_stage("before_save", repo.hooks, ctx)
    out = ctx.values
    if repo.owner_id is not None:
        out["created_by_id"] = repo.owner_id
    if repo.tenant_id is not None:
        out["tenant_id"] = repo.tenant_id
    if repo.policy is not None:
        repo.policy.check_new_row(out)
    related = await repo._pop_related(out)
    await repo._check_references(out)
    return {**out, **related}, ctx
