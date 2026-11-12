"""Per-row custom fields (C2): validation of the definitions and promotion to a real column.

An entity may opt in to one JSONB column, `custom_fields`, holding values for the fields declared in
`SpecEntity.custom_fields.defs`. A def can later be PROMOTED to a typed column: `promote` is a pure
function (spec in, spec + plan out); the plan renders the Alembic migration that moves the data and
can be downgraded. Pure logic: no database, no clock, no randomness.
"""

import json
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.core import naming
from app.core.spec_models import Spec, SpecCustomFieldDef, SpecEntity, SpecField

Add = Callable[[str, str, str], None]

COLUMN = "custom_fields"
CUSTOM_TYPES = ("string", "int", "float", "bool", "date", "datetime")
MAX_DEFS = 100
MAX_KEYS_LIMIT = 200
MAX_BYTES_LIMIT = 65_536
DEFAULT_STRING_LENGTH = 255  # same fallback as a real string column, so promotion never truncates
INT_RANGE = (-(2**31), 2**31 - 1)  # an Integer column; keeps promotion lossless
_MAX_ENUM_VALUES = 100
_ENUM_VALUE_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")

# custom type -> (SpecField type, postgres cast of the ->> text value, SQLAlchemy column expression)
_PROMOTION: dict[str, tuple[str, str, str]] = {
    "string": ("string", "", "sa.String({length})"),
    "int": ("integer", "integer", "sa.Integer()"),
    "float": ("float", "double precision", "sa.Float()"),
    "bool": ("boolean", "boolean", "sa.Boolean()"),
    "date": ("date", "date", "sa.Date()"),
    "datetime": ("datetime", "timestamptz", "sa.DateTime(timezone=True)"),
}


class CustomFieldError(ValueError):
    """A promotion that cannot be planned (unknown entity or def, collision)."""


def enabled_defs(entity: SpecEntity) -> list[SpecCustomFieldDef]:
    cf = entity.custom_fields
    return list(cf.defs) if cf is not None and cf.enabled else []


def is_enabled(entity: SpecEntity) -> bool:
    return entity.custom_fields is not None and entity.custom_fields.enabled


def check_custom_fields(entity: SpecEntity, path: str, add: Add) -> None:
    """Stable codes: custom_field_bad_name, custom_field_collision, custom_field_bad_type,
    custom_field_too_many, custom_field_bad_limit, custom_field_bad_option."""
    cf = entity.custom_fields
    if cf is None:
        return
    p = f"{path}.custom_fields"
    if not 1 <= cf.max_keys <= MAX_KEYS_LIMIT:
        add(f"{p}.max_keys", "custom_field_bad_limit", f"must be between 1 and {MAX_KEYS_LIMIT}")
    if not 1 <= cf.max_bytes <= MAX_BYTES_LIMIT:
        add(f"{p}.max_bytes", "custom_field_bad_limit", f"must be between 1 and {MAX_BYTES_LIMIT}")
    if len(cf.defs) > MAX_DEFS:
        add(f"{p}.defs", "custom_field_too_many", f"at most {MAX_DEFS} custom fields are allowed")
    elif cf.enabled and len(cf.defs) > cf.max_keys:
        add(f"{p}.defs", "custom_field_too_many", f"more definitions than max_keys ({cf.max_keys})")
    if cf.enabled and any(f.name == COLUMN for f in entity.fields):
        add(f"{path}.fields", "custom_field_collision", f"a real field named {COLUMN!r} collides with the custom fields column")
    real = {f.name for f in entity.fields} | set(naming.AUTO_FIELDS) | {COLUMN}
    if entity.options.soft_delete:
        real.add(naming.SOFT_DELETE_FIELD[0])
    seen: set[str] = set()
    for i, d in enumerate(cf.defs):
        q = f"{p}.defs[{i}]"
        if len(d.name) > naming.MAX_IDENTIFIER_LENGTH or not naming.SNAKE_NAME_RE.fullmatch(d.name):
            add(f"{q}.name", "custom_field_bad_name", "must be snake_case, at most 63 characters")
        elif naming.is_python_reserved(d.name) or naming.is_sql_reserved(d.name):
            add(f"{q}.name", "custom_field_bad_name", f"{d.name!r} is a reserved word")
        elif naming.is_reserved_attribute(d.name):
            add(f"{q}.name", "custom_field_bad_name", f"{d.name!r} clashes with a generated attribute")
        if d.name in real:
            add(f"{q}.name", "custom_field_collision", f"{d.name!r} collides with a real or reserved field")
        elif d.name in seen:
            add(f"{q}.name", "custom_field_collision", f"{d.name!r} is defined twice")
        seen.add(d.name)
        if d.type not in CUSTOM_TYPES:
            add(f"{q}.type", "custom_field_bad_type", f"must be one of {', '.join(CUSTOM_TYPES)}")
            continue
        _check_options(d, q, add)


def _check_options(d: SpecCustomFieldDef, q: str, add: Add) -> None:
    if d.max_length is not None:
        if d.type != "string":
            add(f"{q}.max_length", "custom_field_bad_option", "only string custom fields have a max_length")
        elif not 1 <= d.max_length <= 10_000:
            add(f"{q}.max_length", "custom_field_bad_option", "must be between 1 and 10000")
    if d.enum_values is not None:
        if d.type != "string":
            add(f"{q}.enum_values", "custom_field_bad_option", "only string custom fields have enum_values")
        elif not d.enum_values or len(d.enum_values) > _MAX_ENUM_VALUES:
            add(f"{q}.enum_values", "custom_field_bad_option", f"needs 1 to {_MAX_ENUM_VALUES} values")
        elif len(set(d.enum_values)) != len(d.enum_values) or not all(
            _ENUM_VALUE_RE.fullmatch(v) for v in d.enum_values
        ):
            add(f"{q}.enum_values", "custom_field_bad_option", "values must be unique and match [A-Za-z0-9_.-]{1,64}")


# --- promotion --------------------------------------------------------------------------


def _q(x: str) -> str:
    return '"' + x.replace('"', '""') + '"'


@dataclass(frozen=True)
class PromotionPlan:
    """What promoting one custom field does to the table. Renders the Alembic revision."""

    entity: str
    table: str
    name: str
    custom_type: str
    column_type: str  # SpecField type
    required: bool
    max_length: int | None
    enum_values: tuple[str, ...] | None

    @property
    def cast(self) -> str:
        return _PROMOTION[self.custom_type][1]

    @property
    def _value_sql(self) -> str:
        text = f"{COLUMN}->>'{self.name}'"
        return f"({text})::{self.cast}" if self.cast else text

    @property
    def sa_column_type(self) -> str:
        length = (self.max_length or DEFAULT_STRING_LENGTH) if self.column_type != "enum" else 64
        return _PROMOTION[self.custom_type][2].format(length=length)

    def upgrade_sql(self) -> list[str]:
        """The data-moving statements, in order (advisory text for the planner; the revision is authoritative)."""
        t, n = _q(self.table), _q(self.name)
        has_key = f"jsonb_exists({COLUMN}, '{self.name}')"
        sql = [
            f"ALTER TABLE {t} ADD COLUMN {n} {_PROMOTION[self.custom_type][1] or 'varchar'} NULL",
            f"UPDATE {t} SET {n} = {self._value_sql} WHERE {has_key}",
        ]
        if self.required:
            sql.append(f"-- guard: fail if any row still has NULL {n}")
        sql.append(f"UPDATE {t} SET {COLUMN} = {COLUMN} - '{self.name}' WHERE {has_key}")
        if self.required:
            sql.append(f"ALTER TABLE {t} ALTER COLUMN {n} SET NOT NULL")
        return sql

    def downgrade_sql(self) -> list[str]:
        t, n = _q(self.table), _q(self.name)
        return [
            f"UPDATE {t} SET {COLUMN} = {COLUMN} || jsonb_build_object('{self.name}', {n}) WHERE {n} IS NOT NULL",
            f"ALTER TABLE {t} DROP COLUMN {n}",
        ]

    def render_migration(self, revision: str, down_revision: str | None) -> str:
        # Identifiers are validated snake_case (never reserved), so the revision leaves them unquoted.
        t, n = self.table, self.name
        if not (re.fullmatch(r"[a-z][a-z0-9_]*", t) and re.fullmatch(r"[a-z][a-z0-9_]*", n)):
            raise ValueError("promotion needs validated snake_case table and field names")
        has_key = f"jsonb_exists({COLUMN}, '{n}')"
        value = self._value_sql
        up = [
            f'    op.add_column("{t}", sa.Column("{n}", {self.sa_column_type}, nullable=True))',
            f'    op.execute("UPDATE {t} SET {n} = {value} WHERE {has_key}")',
        ]
        if self.required:
            up += [
                "    missing = op.get_bind().execute(",
                f'        sa.text("SELECT count(*) FROM {t} WHERE {n} IS NULL")',
                "    ).scalar_one()",
                "    if missing:",
                "        raise RuntimeError(",
                f'            f"cannot make {t}.{n} NOT NULL: {{missing}} row(s) have no value"',
                '            " for this custom field; fill them first"',
                "        )",
            ]
        up.append(f'    op.execute("UPDATE {t} SET {COLUMN} = {COLUMN} - \'{n}\' WHERE {has_key}")')
        if self.required:
            up.append(f'    op.alter_column("{t}", "{n}", nullable=False)')
        down = [
            "    op.execute(",
            f'        "UPDATE {t} SET {COLUMN} = {COLUMN} || jsonb_build_object(\'{n}\', {n}) "',
            f'        "WHERE {n} IS NOT NULL"',
            "    )",
            f'    op.drop_column("{t}", "{n}")',
        ]
        return "\n".join(
            [
                f'"""promote custom field {self.entity}.{n} to a column',
                "",
                f"Revision ID: {revision}",
                f"Revises: {down_revision or ''}",
                '"""',
                "",
                "from collections.abc import Sequence",
                "",
                "import sqlalchemy as sa",
                "from alembic import op",
                "",
                f"revision: str = {revision!r}",
                f"down_revision: str | None = {down_revision!r}",
                "branch_labels: str | Sequence[str] | None = None",
                "depends_on: str | Sequence[str] | None = None",
                "",
                "",
                "def upgrade() -> None:",
                *up,
                "",
                "",
                "def downgrade() -> None:",
                *down,
                "",
            ]
        )


def promotion_column_type(d: SpecCustomFieldDef) -> str:
    """The SpecField type a promoted def becomes. KeyError for an unknown custom type."""
    if d.type == "string" and d.enum_values:
        return "enum"
    return _PROMOTION[d.type][0]


def promote(spec: Spec, entity_name: str, field_name: str) -> tuple[Spec, PromotionPlan]:
    """Turn custom field `field_name` of `entity_name` into a real column. Returns a new spec (the input
    is untouched) and the plan. Raises CustomFieldError when the entity or def is missing or the name
    now collides with a real field."""
    new = spec.model_copy(deep=True)
    entity = next((e for e in new.entities if e.name == entity_name), None)
    if entity is None:
        raise CustomFieldError(f"no entity named {entity_name!r}")
    cf = entity.custom_fields
    if cf is None or not cf.enabled:
        raise CustomFieldError(f"{entity_name} has no custom fields enabled")
    d = next((x for x in cf.defs if x.name == field_name), None)
    if d is None:
        raise CustomFieldError(f"{entity_name} has no custom field named {field_name!r}")
    if d.type not in _PROMOTION:
        raise CustomFieldError(f"custom field {field_name!r} has unknown type {d.type!r}")
    if any(f.name == field_name for f in entity.fields):
        raise CustomFieldError(f"{entity_name} already has a real field named {field_name!r}")
    column_type = promotion_column_type(d)
    entity.fields.append(
        SpecField(
            name=d.name,
            type=column_type,
            required=d.required,
            max_length=d.max_length if column_type == "string" else None,
            enum_values=list(d.enum_values) if column_type == "enum" and d.enum_values else None,
        )
    )
    cf.defs = [x for x in cf.defs if x.name != field_name]
    plan = PromotionPlan(
        entity=entity.name,
        table=entity.table_name,
        name=d.name,
        custom_type=d.type,
        column_type=column_type,
        required=d.required,
        max_length=d.max_length,
        enum_values=tuple(d.enum_values) if d.enum_values else None,
    )
    return new, plan


# --- promotion pre-flight (pure: the caller supplies sample values, nothing touches a customer DB) ---

MAX_SAMPLES = 1000
_INT_RE = re.compile(r"\s*[+-]?[0-9]+\s*")
# What Postgres accepts for ::double precision, minus nan/inf (rejected here) and underscores (rejected by PG).
_FLOAT_RE = re.compile(r"\s*[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?\s*")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_DATETIME_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}([T ][0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]{1,6})?)?)?(Z|[+-][0-9]{2}(:[0-9]{2})?)?"
)
_BOOL_WORDS = frozenset({"true", "false", "t", "f", "yes", "no", "y", "n", "on", "off", "1", "0"})


@dataclass(frozen=True)
class PromoteProblem:
    """severity `error` blocks the promotion; `warning` is information (type change, no default)."""

    code: str
    message: str
    sample_index: int | None = None
    severity: str = "error"


def _text_of(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):  # jsonb ->> renders json text, not Python repr
        return json.dumps(v, ensure_ascii=False)
    return v if isinstance(v, str) else str(v)


def _cast_problem(d: SpecCustomFieldDef, v: Any) -> tuple[str, str] | None:
    """(code, message) when the value would not survive the migration's `->>` text cast."""
    t = d.type
    if t == "int":
        if isinstance(v, bool) or not (
            isinstance(v, int) or (isinstance(v, str) and _INT_RE.fullmatch(v))
        ):
            return "custom_field_promote_bad_value", "not an integer"
        try:
            n = int(v) if isinstance(v, str) else v
        except ValueError:  # > 4300 digits
            return "custom_field_promote_int_out_of_range", f"outside {INT_RANGE[0]}..{INT_RANGE[1]}"
        if not INT_RANGE[0] <= n <= INT_RANGE[1]:
            return "custom_field_promote_int_out_of_range", f"outside {INT_RANGE[0]}..{INT_RANGE[1]}"
    elif t == "float":
        try:
            ok = (
                not isinstance(v, bool)
                and (isinstance(v, (int, float)) or (isinstance(v, str) and _FLOAT_RE.fullmatch(v)))
                and math.isfinite(float(v))
            )
        except (ValueError, OverflowError):
            ok = False
        if not ok:
            return "custom_field_promote_bad_value", "not a number"
    elif t == "bool":
        if not (isinstance(v, bool) or (isinstance(v, (str, int)) and str(v).strip().lower() in _BOOL_WORDS)):
            return "custom_field_promote_bad_value", "not a boolean"
    elif t == "date":
        try:
            if not (isinstance(v, str) and _DATE_RE.fullmatch(v)):
                raise ValueError
            date.fromisoformat(v)
        except ValueError:
            return "custom_field_promote_bad_date", "not an ISO date (YYYY-MM-DD)"
    elif t == "datetime":
        try:
            if not (isinstance(v, str) and _DATETIME_RE.fullmatch(v)):
                raise ValueError
            datetime.fromisoformat(v)
        except ValueError:
            return "custom_field_promote_bad_datetime", "not an ISO 8601 date-time"
    else:  # string
        text = _text_of(v)
        limit = d.max_length or DEFAULT_STRING_LENGTH
        if d.enum_values:
            if text not in d.enum_values:
                return "custom_field_promote_not_in_enum", "not one of the allowed values"
            limit = 64
        if len(text) > limit:
            return "custom_field_promote_too_long", f"longer than {limit} characters"
    return None


def preflight_cast(d: SpecCustomFieldDef, sample_values: Sequence[Any]) -> list[PromoteProblem]:
    """Would these sample values (None = row has no value) survive promoting `d` to a column?
    Pure; reports at most one problem per sample and never echoes a value. Stable codes:
    custom_field_promote_required_without_default, _bad_value, _int_out_of_range, _too_long,
    _not_in_enum, _bad_date, _bad_datetime."""
    out: list[PromoteProblem] = []
    for i, v in enumerate(sample_values[:MAX_SAMPLES]):
        if v is None:
            if d.required:
                out.append(
                    PromoteProblem(
                        "custom_field_promote_required_without_default",
                        "a row has no value and the column would be NOT NULL (custom fields have no default)",
                        i,
                    )
                )
            continue
        bad = _cast_problem(d, v)
        if bad is not None:
            out.append(PromoteProblem(bad[0], bad[1], i))
    return out


def check_promotable(
    spec: Spec, entity: str, name: str, sample_values: Sequence[Any] | None = None
) -> list[PromoteProblem]:
    """Static checks on the spec (always) plus the sample cast check (when samples are given)."""
    try:
        promote(spec, entity, name)
    except CustomFieldError as exc:
        return [PromoteProblem("custom_field_promote_unavailable", str(exc))]
    ent = next(e for e in spec.entities if e.name == entity)
    d = next(x for x in enabled_defs(ent) if x.name == name)
    out: list[PromoteProblem] = []
    target = promotion_column_type(d)
    if target != d.type:
        out.append(
            PromoteProblem(
                "custom_field_promote_type_change",
                f"custom type {d.type!r} becomes column type {target!r}",
                severity="warning",
            )
        )
    elif d.type in ("int", "float", "bool", "date", "datetime"):
        out.append(
            PromoteProblem(
                "custom_field_promote_type_change",
                f"values are cast from text to {_PROMOTION[d.type][1]}",
                severity="warning",
            )
        )
    if d.required and not sample_values:
        out.append(
            PromoteProblem(
                "custom_field_promote_required_without_default",
                "the column would be NOT NULL: the migration fails if any row has no value",
                severity="warning",
            )
        )
    if sample_values is not None and len(sample_values) >= MAX_SAMPLES:
        out.append(
            PromoteProblem(
                "custom_field_promote_sample_capped",
                f"only the first {MAX_SAMPLES} rows are checked; later rows may still fail the migration",
                severity="warning",
            )
        )
    if sample_values is not None:
        out += preflight_cast(d, sample_values)
    return out


def is_proven(problems: Sequence[PromoteProblem], sample_values: Sequence[Any] | None) -> bool:
    """True only when samples were checked, covered every row we could be given (not capped at
    MAX_SAMPLES), and nothing blocks. Never true for 'no samples': the migration is then unproven."""
    return (
        bool(sample_values)
        and sample_values is not None
        and len(sample_values) < MAX_SAMPLES
        and not any(p.severity == "error" for p in problems)
    )
