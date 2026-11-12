"""Data import core (generated copy of the platform parser): CSV parsing with hard caps, mapping, typed coercion, validation, dedupe.

Pure: no database, no clock, no network. Values are stored VERBATIM; nothing here rewrites a cell.
Anything that writes cells back out (a CSV/spreadsheet export) must pass them through
`neutralize_formula` so a cell such as `=HYPERLINK(...)` is never executed by a spreadsheet.
"""

import csv
import hashlib
import io
import json
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class SpecField:
    """One importable field (generated table, see app/imports/fields.py)."""

    name: str
    type: str
    required: bool = False
    unique: bool = False
    default: Any = None
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    enum_values: tuple[str, ...] | None = None


@dataclass(frozen=True)
class SpecEntity:
    name: str
    fields: tuple[SpecField, ...]

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20_000
MAX_COLUMNS = 100
MAX_CELL_CHARS = 100_000
DELIMITERS = (",", ";", "\t")

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_TRUE = {"true", "t", "yes", "y", "1"}
_FALSE = {"false", "f", "no", "n", "0"}
_INT_RE = re.compile(r"^[+-]?\d+$")
_INT32 = (-(2**31), 2**31 - 1)
_INT64 = (-(2**63), 2**63 - 1)


class ImportDataError(Exception):
    """A file-level failure with a stable code (import_too_large, import_bad_csv, import_bad_mapping)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ParsedCsv:
    headers: list[str]
    rows: list[dict[str, str]]  # header -> verbatim cell, one dict per data row (row_no = index + 1)


@dataclass(frozen=True)
class FieldError:
    field: str
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"field": self.field, "code": self.code, "message": self.message}


@dataclass
class RowResult:
    row_no: int
    raw: dict[str, str]
    record: dict[str, Any] | None
    errors: list[FieldError] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.record is not None and not self.errors


def neutralize_formula(cell: object) -> object:
    """Spreadsheet-injection guard for EXPORTS: a text cell starting with = + - @ tab or CR gets a
    leading apostrophe. Non-text values pass through unchanged."""
    if isinstance(cell, str) and cell.startswith(_FORMULA_PREFIXES):
        return "'" + cell
    return cell


# -- parsing ------------------------------------------------------------------------------------


def _decode(data: bytes) -> str:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportDataError("import_bad_csv", "the file is not valid UTF-8 text") from exc
    if "\x00" in text:
        raise ImportDataError("import_bad_csv", "the file contains NUL bytes")
    return text


def sniff_delimiter(first_line: str) -> str:
    """The most frequent of , ; tab in the header line (ties and none: comma). Quoted text is ignored."""
    unquoted = re.sub(r'"[^"]*"', "", first_line)
    counts = {d: unquoted.count(d) for d in DELIMITERS}
    best = max(DELIMITERS, key=lambda d: counts[d])
    return best if counts[best] > 0 else ","


def parse_csv(data: bytes, max_bytes: int = MAX_BYTES, max_rows: int = MAX_ROWS) -> ParsedCsv:
    if len(data) > max_bytes:
        raise ImportDataError("import_too_large", f"the file is larger than {max_bytes} bytes")
    text = _decode(data)
    if not text.strip():
        raise ImportDataError("import_bad_csv", "the file is empty")
    first_line = text.splitlines()[0]
    delimiter = sniff_delimiter(first_line)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    try:
        header_row = next(reader)
    except (StopIteration, csv.Error) as exc:
        raise ImportDataError("import_bad_csv", "the header row cannot be read") from exc
    headers = [h.strip() for h in header_row]
    if len(headers) > MAX_COLUMNS:
        raise ImportDataError("import_too_large", f"more than {MAX_COLUMNS} columns")
    if any(not h for h in headers):
        raise ImportDataError("import_bad_csv", "a column header is empty")
    if len({h.lower() for h in headers}) != len(headers):
        raise ImportDataError("import_bad_csv", "two columns have the same header")
    rows: list[dict[str, str]] = []
    try:
        for cells in reader:
            if not cells or all(c == "" for c in cells):
                continue  # blank line
            if len(rows) >= max_rows:
                raise ImportDataError("import_too_large", f"more than {max_rows} rows")
            if len(cells) > len(headers):
                raise ImportDataError(
                    "import_bad_csv", f"row {len(rows) + 1} has more cells than the header"
                )
            if any(len(c) > MAX_CELL_CHARS for c in cells):
                raise ImportDataError("import_too_large", f"a cell in row {len(rows) + 1} is too long")
            cells = cells + [""] * (len(headers) - len(cells))
            rows.append(dict(zip(headers, cells, strict=True)))
    except csv.Error as exc:
        raise ImportDataError("import_bad_csv", f"malformed CSV near row {len(rows) + 1}: {exc}") from exc
    return ParsedCsv(headers, rows)


# -- mapping ------------------------------------------------------------------------------------


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def suggest_mapping(headers: list[str], entity: SpecEntity) -> dict[str, str]:
    """entity field -> csv header, matched ignoring case, underscores, spaces and dashes."""
    by_norm: dict[str, str] = {}
    for h in headers:
        by_norm.setdefault(_norm(h), h)
    out: dict[str, str] = {}
    for f in entity.fields:
        hit = by_norm.get(_norm(f.name))
        if hit is not None:
            out[f.name] = hit
    return out


def clean_mapping(mapping: object, headers: list[str], entity: SpecEntity) -> dict[str, str]:
    """Validate a client mapping (entity field -> csv header). Unknown fields or headers are refused."""
    if not isinstance(mapping, dict):
        raise ImportDataError("import_bad_mapping", "mapping must be an object")
    fields = {f.name for f in entity.fields}
    out: dict[str, str] = {}
    for key, header in mapping.items():
        if key not in fields:
            raise ImportDataError("import_bad_mapping", f"unknown field {str(key)[:60]!r}")
        if header is None or header == "":
            continue  # explicitly unmapped
        if not isinstance(header, str) or header not in headers:
            raise ImportDataError("import_bad_mapping", f"unknown column for field {key!r}")
        out[key] = header
    return out


# -- coercion -----------------------------------------------------------------------------------


class _Bad(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _check_range(num: float | Decimal, f: SpecField) -> None:
    if f.min_value is not None and num < Decimal(str(f.min_value)):
        raise _Bad("below_min", f"must be at least {f.min_value:g}")
    if f.max_value is not None and num > Decimal(str(f.max_value)):
        raise _Bad("above_max", f"must be at most {f.max_value:g}")


def _coerce_value(value: Any, f: SpecField) -> Any:
    t = f.type
    if t in ("string", "text"):
        s = value if isinstance(value, str) else str(value)
        if f.max_length is not None and len(s) > f.max_length:
            raise _Bad("too_long", f"at most {f.max_length} characters")
        return s
    if t in ("integer", "bigint"):
        if isinstance(value, bool):
            raise _Bad("invalid_integer", "not a whole number")
        if isinstance(value, int):
            n = value
        elif isinstance(value, str) and _INT_RE.match(value.strip()):
            n = int(value.strip())
        else:
            raise _Bad("invalid_integer", "not a whole number")
        lo, hi = _INT32 if t == "integer" else _INT64
        if not lo <= n <= hi:
            raise _Bad("out_of_range", "number is out of range")
        _check_range(Decimal(n), f)
        return n
    if t in ("float", "decimal"):
        if isinstance(value, bool):
            raise _Bad("invalid_number", "not a number")
        try:
            d = Decimal(value.strip() if isinstance(value, str) else str(value))
        except InvalidOperation as exc:
            raise _Bad("invalid_number", "not a number") from exc
        if not d.is_finite():
            raise _Bad("invalid_number", "not a finite number")
        if not -400 <= d.adjusted() <= 400:
            raise _Bad("out_of_range", "number is out of range")
        _check_range(d, f)
        if t == "float":
            x = float(d)
            if not math.isfinite(x):
                raise _Bad("invalid_number", "number is out of range")
            return x
        return format(d, "f")
    if t == "boolean":
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in _TRUE:
            return True
        if s in _FALSE:
            return False
        raise _Bad("invalid_boolean", "expected true or false")
    if t == "date":
        s = str(value).strip()
        try:
            if len(s) != 10:
                raise ValueError
            return date.fromisoformat(s).isoformat()
        except ValueError as exc:
            raise _Bad("invalid_date", "expected YYYY-MM-DD") from exc
    if t == "datetime":
        s = str(value).strip()
        try:
            dt = datetime.fromisoformat(s)
        except ValueError as exc:
            raise _Bad("invalid_datetime", "expected an ISO 8601 date and time") from exc
        return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC).isoformat()
    if t == "uuid":
        try:
            return str(uuid.UUID(str(value).strip()))
        except ValueError as exc:
            raise _Bad("invalid_uuid", "not a UUID") from exc
    if t == "json":
        try:
            parsed = json.loads(value, parse_constant=_reject_constant) if isinstance(value, str) else value
            if _depth(parsed) > 32:
                raise _Bad("invalid_json", "JSON is nested too deeply")
            json.dumps(parsed, allow_nan=False).encode("utf-8")
        except (ValueError, RecursionError, TypeError) as exc:
            raise _Bad("invalid_json", "not valid JSON") from exc
        return parsed
    if t == "enum":
        s = str(value).strip()
        if not f.enum_values or s not in f.enum_values:
            raise _Bad("invalid_enum", "not one of: " + ", ".join(f.enum_values or []))
        return s
    raise _Bad("unsupported_type", f"fields of type {t!r} cannot be imported")


def _reject_constant(name: str) -> Any:
    raise ValueError(name)


def _depth(v: Any, d: int = 0) -> int:
    if d > 32:
        return d
    if isinstance(v, dict):
        return max([_depth(x, d + 1) for x in v.values()] or [d + 1])
    if isinstance(v, list):
        return max([_depth(x, d + 1) for x in v] or [d + 1])
    return d


def coerce(value: Any, f: SpecField) -> Any:
    """The typed, JSON-safe value for one field, or raises ValueError(code) with the stable code.

    A blank value is None, unless the field is required (error `required`) or has a default."""
    try:
        return _coerce_checked(value, f)
    except _Bad as bad:
        raise ValueError(bad.code) from bad


def _coerce_checked(value: Any, f: SpecField) -> Any:
    if _is_blank(value):
        if f.default is not None:
            return _coerce_value(f.default, f)
        if f.required:
            raise _Bad("required", "a value is required")
        return None
    return _coerce_value(value, f)


def validate_values(values: dict[str, Any], entity: SpecEntity) -> RowResult:
    """Validate {field: raw value} (fields absent from the dict count as blank)."""
    record: dict[str, Any] = {}
    errors: list[FieldError] = []
    for f in entity.fields:
        try:
            record[f.name] = _coerce_checked(values.get(f.name), f)
        except _Bad as bad:
            errors.append(FieldError(f.name, bad.code, bad.message))
    return RowResult(0, {}, None if errors else record, errors)


def values_from_raw(raw: dict[str, str], mapping: dict[str, str]) -> dict[str, Any]:
    return {fname: raw.get(header) for fname, header in mapping.items()}


def validate_rows(
    rows: list[dict[str, str]], mapping: dict[str, str], entity: SpecEntity
) -> list[RowResult]:
    out: list[RowResult] = []
    for i, raw in enumerate(rows, start=1):
        res = validate_values(values_from_raw(raw, mapping), entity)
        out.append(RowResult(i, raw, res.record, res.errors))
    return out


def dedupe_key(entity: SpecEntity, record: dict[str, Any], key_fields: list[str] | None = None) -> str:
    """sha256 over canonical JSON of the entity's unique fields (or the whole record when it has none,
    or when every unique field is empty in this record). Blank values are left out so the key does not
    depend on which columns were mapped."""
    names = key_fields if key_fields is not None else [f.name for f in entity.fields if f.unique]
    picked = {n: record[n] for n in sorted(names) if record.get(n) is not None}
    if not picked:
        picked = {k: v for k, v in sorted(record.items()) if v is not None}
    blob = json.dumps(
        {"entity": entity.name, "key": picked}, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class DedupeKeys:
    """Dedupe keys for one caller. A key is `(kind, hash)`. `plain` keys use only fields the caller may read.
    A record whose unique key includes a field the caller may not read gets a `guarded` key over the full
    record: a match on it is reported as a generic rejection, never as a duplicate."""

    def __init__(self, writable: SpecEntity, hidden_read: frozenset[str] | set[str]) -> None:
        self.writable = writable
        self.readable = SpecEntity(
            writable.name, tuple(f for f in writable.fields if f.name not in hidden_read)
        )
        self.guarded_names = sorted(f.name for f in writable.fields if f.unique and f.name in hidden_read)
        self.json_fields = {f.name for f in writable.fields if f.type == "json"}

    def is_guarded(self, record: dict[str, Any]) -> bool:
        return any(record.get(n) is not None for n in self.guarded_names)

    def of(self, record: dict[str, Any]) -> tuple[str, str]:
        if self.is_guarded(record):
            return ("guarded", dedupe_key(self.writable, record))
        return ("plain", dedupe_key(self.readable, record))

    def probe_names(self, record: dict[str, Any]) -> tuple[str, ...]:
        """The columns the key is built from for this record (a database lookup narrows on these)."""
        entity = self.writable if self.is_guarded(record) else self.readable
        unique = [f.name for f in entity.fields if f.unique]
        names = [n for n in sorted(unique) if record.get(n) is not None]
        if not names:
            names = [f.name for f in sorted(entity.fields, key=lambda f: f.name) if record.get(f.name) is not None]
        return tuple(n for n in names if n not in self.json_fields)
