"""Validation for the `seed` section (seed profiles). Issues go through `add(path, code, message)`.

The seed plan is the one thing an AI may fill in later, so it is closed: every generator type, its keys,
the columns it may touch, the ceilings and the value shapes are checked here. Nothing in a plan is ever
evaluated; unknown keys never reach this module (the schema forbids them) and keys that do not belong to
the generator's type are refused here."""

import re
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core import naming
from app.core.seed_engine import (
    EMAIL_DOMAIN,
    GENERATOR_TYPES,
    MAX_WORD_LENGTH,
    MAX_WORDS,
    email_text,
    reachable_states,
    sequence_text,
)
from app.core.spec_models import (
    Spec,
    SpecEntity,
    SpecField,
    SpecSeedEntity,
    SpecSeedGenerator,
    SpecSeedProfile,
    SpecStateMachine,
)
from app.core.validation_authorization import authz_active
from app.core.validation_runtime import looks_secret

Add = Callable[[str, str, str], None]

SEED_TABLES = ("seed_rows",)
MAX_PROFILES = 5
MAX_TENANTS = 20
MAX_ROWS_PER_ENTITY = 10_000  # after multiplying by the tenants
MAX_ROWS_PER_PROFILE = 50_000
MAX_LIST_VALUES = 100
MAX_TEXT_LENGTH = 200
MAX_PREFIX_LENGTH = 40
MAX_FIELDS_PER_ENTITY = 100
MAX_DECIMAL_PLACES = 6
MAX_DECIMAL_DIGITS = 12  # integer digits: the column is Numeric(18, 6)
MAX_SEED = 2**31 - 1
NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,23}")
PREFIX_RE = re.compile(r"[A-Za-z0-9_.-]{0,40}")
EMAIL_PREFIX_RE = re.compile(r"[a-z][a-z0-9]{0,19}")
SAFE_DOMAIN_RE = re.compile(r".*@([A-Za-z0-9-]+\.)*(test|example|invalid|localhost)$|.*@example\.(com|org|net)$")

SEEDABLE = {"string", "text", "integer", "bigint", "float", "decimal", "boolean", "date", "datetime", "enum"}
_INT_TYPES = {"integer", "bigint"}
_INT_LIMITS = {"integer": (-(2**31), 2**31 - 1), "bigint": (-(2**63), 2**63 - 1)}

# generator type -> field types it can fill; keys it accepts besides `type`
GENERATORS: dict[str, tuple[set[str], set[str]]] = {
    "constant": (SEEDABLE, {"value"}),
    "one_of": (SEEDABLE, {"values"}),
    "sequence": ({"string", "text"} | _INT_TYPES, {"prefix", "start", "width"}),
    "int_range": (_INT_TYPES, {"min", "max"}),
    "decimal_range": ({"decimal", "float"}, {"min", "max", "places"}),
    "date_range": ({"date", "datetime"}, {"min", "max"}),
    "bool_ratio": ({"boolean"}, {"ratio"}),
    "words": ({"string", "text"}, {"min_words", "max_words"}),
    "email": ({"string", "text"}, {"prefix"}),
    "reference": (set(), {"entity", "pick"}),
    "state": ({"enum"}, {"weights"}),
}
_KEYS = (
    "value", "values", "prefix", "start", "width", "min", "max", "places", "ratio",
    "min_words", "max_words", "entity", "pick", "weights",
)
# generators whose value differs for every row: usable on a unique column
INJECTIVE = {"sequence", "email"}


def seed_active(spec: Spec) -> bool:
    return bool(spec.seed)


def multi_tenant(spec: Spec) -> bool:
    return bool(spec.auth is not None and spec.auth.enabled and spec.auth.multi_tenant)


def tenant_scoped(spec: Spec, entity: SpecEntity) -> bool:
    """Whether the generated entity has a tenant_id (same rule as generator/context.py)."""
    if not multi_tenant(spec) or spec.auth is None:
        return False
    if authz_active(spec):
        return True
    if not spec.auth.permissions:
        return False
    return any(
        p.entity == entity.name and p.row_rule == "tenant" and p.operation in entity.options.operations
        for p in spec.auth.permissions
    )


def foreign_keys(spec: Spec) -> dict[str, dict[str, tuple[str, bool, bool]]]:
    """entity -> {fk column: (target entity, required, unique)} of the one_to_many / one_to_one relations."""
    out: dict[str, dict[str, tuple[str, bool, bool]]] = {}
    for rel in spec.relations:
        if rel.kind in ("one_to_many", "one_to_one"):
            out.setdefault(rel.to_entity, {})[naming.fk_column_name(rel.to_name)] = (
                rel.from_entity,
                rel.required,
                rel.kind == "one_to_one",
            )
    return out


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        out = Decimal(str(value))
    except InvalidOperation:
        return None
    return out if out.is_finite() else None


def _iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def check_seed(spec: Spec, entities: dict[str, SpecEntity], add: Add) -> None:
    if not spec.seed:
        return
    if len(spec.seed) > MAX_PROFILES:
        add("seed", "too_many", f"at most {MAX_PROFILES} seed profiles")
        return
    machines = {m.entity: m for m in spec.state_machines}
    fks = foreign_keys(spec)
    seen: set[str] = set()
    for i, prof in enumerate(spec.seed):
        p = f"seed[{i}]"
        if not NAME_RE.fullmatch(prof.name):
            add(f"{p}.name", "invalid_value", "use lowercase letters, digits and '_' (max 24)")
        elif prof.name in seen:
            add(f"{p}.name", "duplicate_name", f"profile {prof.name} is listed twice")
        seen.add(prof.name)
        _check_profile(spec, prof, p, entities, machines, fks, add)


def _check_profile(
    spec: Spec,
    prof: SpecSeedProfile,
    p: str,
    entities: dict[str, SpecEntity],
    machines: dict[str, SpecStateMachine],
    fks: dict[str, dict[str, tuple[str, bool, bool]]],
    add: Add,
) -> None:
    if not 0 <= prof.seed <= MAX_SEED:
        add(f"{p}.seed", "invalid_value", f"seed must be 0 to {MAX_SEED}")
    day = _iso_date(prof.as_of)
    if day is None or not 1990 <= day.year <= 2100:
        add(f"{p}.as_of", "invalid_value", "as_of must be a date like 2026-01-31 (years 1990 to 2100)")
    if not 0 <= prof.tenants <= MAX_TENANTS:
        add(f"{p}.tenants", "invalid_value", f"tenants must be 0 to {MAX_TENANTS}")
    elif prof.tenants > 0 and not multi_tenant(spec):
        add(f"{p}.tenants", "tenants_not_supported", "tenants need auth with multi_tenant switched on")

    plan: dict[str, SpecSeedEntity] = {}
    for j, pe in enumerate(prof.entities):
        ep = f"{p}.entities[{j}]"
        if pe.entity not in entities:
            add(f"{ep}.entity", "unknown_entity", f"no entity named {pe.entity!r}")
        elif pe.entity in plan:
            add(f"{ep}.entity", "duplicate", f"{pe.entity} is listed twice in this profile")
        else:
            plan[pe.entity] = pe
    scoped_names = {n for n, e in entities.items() if tenant_scoped(spec, e)}
    totals: dict[str, int] = {}
    for j, pe in enumerate(prof.entities):
        if pe.entity not in entities or plan.get(pe.entity) is not pe:
            continue
        ep = f"{p}.entities[{j}]"
        if not 0 <= pe.count <= MAX_ROWS_PER_ENTITY:
            add(f"{ep}.count", "invalid_value", f"count must be 0 to {MAX_ROWS_PER_ENTITY}")
            continue
        factor = prof.tenants if pe.entity in scoped_names and prof.tenants > 0 else 1
        totals[pe.entity] = pe.count * factor
        if totals[pe.entity] > MAX_ROWS_PER_ENTITY:
            add(
                f"{ep}.count",
                "too_many_rows",
                f"{pe.entity}: {pe.count} per tenant x {factor} tenants is more than {MAX_ROWS_PER_ENTITY} rows",
            )
        if pe.entity in scoped_names and prof.tenants == 0 and multi_tenant(spec):
            add(f"{ep}.entity", "tenants_required", f"{pe.entity} belongs to a tenant: set tenants to 1 or more")
        _check_entity_plan(spec, prof, pe, ep, entities[pe.entity], machines.get(pe.entity),
                           fks.get(pe.entity, {}), plan, scoped_names, add)
    if sum(totals.values()) > MAX_ROWS_PER_PROFILE:
        add(f"{p}.entities", "too_many_rows", f"a profile may create at most {MAX_ROWS_PER_PROFILE} rows")
    _check_reference_cycles(prof, p, add)


def _check_entity_plan(
    spec: Spec,
    prof: SpecSeedProfile,
    pe: SpecSeedEntity,
    ep: str,
    entity: SpecEntity,
    machine: SpecStateMachine | None,
    fk_cols: dict[str, tuple[str, bool, bool]],
    plan: dict[str, SpecSeedEntity],
    scoped_names: set[str],
    add: Add,
) -> None:
    if len(pe.fields) > MAX_FIELDS_PER_ENTITY:
        add(f"{ep}.fields", "too_many", f"at most {MAX_FIELDS_PER_ENTITY} fields")
        return
    by_name = {f.name: f for f in entity.fields}
    given: dict[str, SpecSeedGenerator] = {}
    rows_total = pe.count * (prof.tenants if pe.entity in scoped_names and prof.tenants > 0 else 1)
    for k, sf in enumerate(pe.fields):
        fp = f"{ep}.fields[{k}]"
        if sf.field in given:
            add(f"{fp}.field", "duplicate", f"{sf.field} is listed twice")
            continue
        gen = sf.generator
        if sf.field in by_name:
            given[sf.field] = gen
            _check_field_generator(spec, entity, by_name[sf.field], gen, fp, machine, rows_total, add)
        elif sf.field in fk_cols:
            given[sf.field] = gen
            _check_reference(spec, prof, pe, gen, fk_cols[sf.field], fp, plan, scoped_names, add)
        else:
            add(
                f"{fp}.field",
                "unknown_field",
                f"{pe.entity} has no field or foreign key named {sf.field!r} "
                "(ids, tenant, owner and timestamps are set by the platform)",
            )
    # required columns must be filled
    for f in entity.fields:
        if f.name in given or (machine is not None and f.name == machine.field):
            continue
        if f.required and f.default is None:
            add(f"{ep}.fields", "required_field_missing", f"{pe.entity}.{f.name} is required: give it a generator")
    for col, (target, required, _unique) in fk_cols.items():
        if required and col not in given:
            add(f"{ep}.fields", "required_field_missing", f"{pe.entity}.{col} is required: give it a reference generator")


def _check_field_generator(
    spec: Spec,
    entity: SpecEntity,
    f: SpecField,
    gen: SpecSeedGenerator,
    fp: str,
    machine: SpecStateMachine | None,
    rows_total: int,
    add: Add,
) -> None:
    gp = f"{fp}.generator"
    kind = gen.type
    if kind not in GENERATOR_TYPES:
        add(f"{gp}.type", "unknown_generator", f"generator type must be one of {', '.join(GENERATOR_TYPES)}")
        return
    types, allowed = GENERATORS[kind]
    is_state = machine is not None and f.name == machine.field
    if f.type not in SEEDABLE:
        add(f"{fp}.field", "unsupported_field_type", f"{f.type} fields cannot be seeded")
        return
    if is_state and kind != "state":
        add(f"{gp}.type", "state_managed", f"{f.name} is the state of a state machine: use the state generator")
        return
    if kind == "state" and not is_state:
        add(f"{gp}.type", "invalid_generator", f"{f.name} is not the state field of a state machine")
        return
    if kind == "reference":
        add(f"{gp}.type", "invalid_generator", f"{f.name} is not a foreign key: reference fills foreign keys only")
        return
    if f.type not in types:
        add(f"{gp}.type", "type_mismatch", f"{kind} cannot fill a {f.type} field ({f.name})")
        return
    _check_keys(gen, allowed, gp, add)
    if looks_secret(f.name) and kind in {"constant", "one_of", "words"}:
        add(f"{fp}.field", "secret_name", "seed data is not a place for secrets")
        return
    if f.unique and kind not in INJECTIVE:
        add(
            f"{gp}.type",
            "unique_not_injective",
            f"{f.name} is unique: use sequence or email so every row gets a different value",
        )
    handler = _CHECKS[kind]
    handler(f, gen, gp, rows_total, machine, add)


def _check_keys(gen: SpecSeedGenerator, allowed: set[str], gp: str, add: Add) -> None:
    for key in _KEYS:
        if getattr(gen, key) is not None and key not in allowed:
            add(f"{gp}.{key}", "unexpected_key", f"{gen.type} does not take {key}")


def _text_ok(value: Any, f: SpecField) -> str | None:
    if not isinstance(value, str):
        return "must be text"
    if len(value) > MAX_TEXT_LENGTH:
        return f"at most {MAX_TEXT_LENGTH} characters"
    if f.max_length is not None and len(value) > f.max_length:
        return f"longer than max_length {f.max_length}"
    if "@" in value and not SAFE_DOMAIN_RE.match(value):
        return f"looks like a real email address: use the {EMAIL_DOMAIN} domain"
    if any(ord(c) < 32 for c in value):
        return "control characters are not allowed"
    return None


def _value_problem(f: SpecField, value: Any) -> str | None:
    """Why `value` cannot be stored in the column, or None."""
    t = f.type
    if t in ("string", "text"):
        return _text_ok(value, f)
    if t == "enum":
        return None if value in (f.enum_values or []) else f"{value!r} is not one of the enum values"
    if t == "boolean":
        return None if isinstance(value, bool) else "must be true or false"
    if t in _INT_TYPES:
        if isinstance(value, bool) or not isinstance(value, int):
            return "must be a whole number"
        low, high = _INT_LIMITS[t]
        problem = None if low <= value <= high else "out of range"
        return problem or _bounds(f, Decimal(value))
    if t in ("float", "decimal"):
        num = _number(value)
        if num is None:
            return "must be a number"
        if abs(num) >= Decimal(10) ** MAX_DECIMAL_DIGITS:
            return "too large"
        if t == "decimal" and -num.as_tuple().exponent > MAX_DECIMAL_PLACES:  # type: ignore[operator]
            return f"at most {MAX_DECIMAL_PLACES} decimal places"
        return _bounds(f, num)
    if t == "date":
        return None if _iso_date(value) is not None else "must be a date like 2026-01-31"
    if t == "datetime":
        if not isinstance(value, str):
            return "must be a timestamp like 2026-01-31T10:00:00+00:00"
        from datetime import datetime

        try:
            datetime.fromisoformat(value)
        except ValueError:
            return "must be a timestamp like 2026-01-31T10:00:00+00:00"
        return None
    return "unsupported type"


def _bounds(f: SpecField, num: Decimal) -> str | None:
    if f.min_value is not None and num < Decimal(str(f.min_value)):
        return f"below min_value {f.min_value}"
    if f.max_value is not None and num > Decimal(str(f.max_value)):
        return f"above max_value {f.max_value}"
    return None


def _check_constant(f: SpecField, gen: SpecSeedGenerator, gp: str, rows: int, m: Any, add: Add) -> None:
    if gen.value is None:
        add(f"{gp}.value", "required", "constant needs a value")
        return
    problem = _value_problem(f, gen.value)
    if problem:
        add(f"{gp}.value", "invalid_value", problem)


def _check_one_of(f: SpecField, gen: SpecSeedGenerator, gp: str, rows: int, m: Any, add: Add) -> None:
    values = gen.values
    if not values:
        add(f"{gp}.values", "required", "one_of needs at least one value")
        return
    if len(values) > MAX_LIST_VALUES:
        add(f"{gp}.values", "too_many", f"at most {MAX_LIST_VALUES} values")
        return
    for k, v in enumerate(values):
        problem = _value_problem(f, v)
        if problem:
            add(f"{gp}.values[{k}]", "invalid_value", problem)


def _check_sequence(f: SpecField, gen: SpecSeedGenerator, gp: str, rows: int, m: Any, add: Add) -> None:
    start = 0 if gen.start is None else gen.start
    width = 0 if gen.width is None else gen.width
    prefix = gen.prefix or ""
    if not 0 <= start <= 10**9:
        add(f"{gp}.start", "invalid_value", "start must be 0 to 1000000000")
    if not 0 <= width <= 12:
        add(f"{gp}.width", "invalid_value", "width must be 0 to 12")
        width = 0
    if f.type in _INT_TYPES:
        if gen.prefix is not None or gen.width is not None:
            add(f"{gp}.prefix", "unexpected_key", "a whole-number sequence takes only start")
        if _INT_LIMITS[f.type][1] < start + rows:
            add(f"{gp}.start", "invalid_value", "the sequence would overflow the column")
        return
    if len(prefix) > MAX_PREFIX_LENGTH or not PREFIX_RE.fullmatch(prefix):
        add(f"{gp}.prefix", "invalid_value", "prefix: letters, digits and _ . - (max 40)")
        return
    longest = len(sequence_text(prefix, start, width, max(rows - 1, 0)))
    if f.max_length is not None and longest > f.max_length:
        add(f"{gp}.prefix", "too_long", f"values up to {longest} characters do not fit max_length {f.max_length}")


def _check_int_range(f: SpecField, gen: SpecSeedGenerator, gp: str, rows: int, m: Any, add: Add) -> None:
    lo, hi = gen.min, gen.max
    if isinstance(lo, str) or isinstance(hi, str) or lo is None or hi is None:
        add(gp, "required", "int_range needs whole-number min and max")
        return
    if lo > hi:
        add(f"{gp}.min", "invalid_range", "min is greater than max")
        return
    for key, v in (("min", lo), ("max", hi)):
        problem = _value_problem(f, v)
        if problem:
            add(f"{gp}.{key}", "invalid_value", problem)


def _check_decimal_range(f: SpecField, gen: SpecSeedGenerator, gp: str, rows: int, m: Any, add: Add) -> None:
    places = 0 if gen.places is None else gen.places
    if not 0 <= places <= MAX_DECIMAL_PLACES:
        add(f"{gp}.places", "invalid_value", f"places must be 0 to {MAX_DECIMAL_PLACES}")
        return
    lo, hi = _number(gen.min), _number(gen.max)
    if lo is None or hi is None:
        add(gp, "required", 'decimal_range needs numeric min and max (decimals as text: "10.50")')
        return
    if lo > hi:
        add(f"{gp}.min", "invalid_range", "min is greater than max")
        return
    for key, v in (("min", lo), ("max", hi)):
        if -v.as_tuple().exponent > places:  # type: ignore[operator]
            add(f"{gp}.{key}", "invalid_value", f"more than {places} decimal places: raise places")
        elif abs(v) >= Decimal(10) ** MAX_DECIMAL_DIGITS:
            add(f"{gp}.{key}", "invalid_value", "too large")
        else:
            problem = _bounds(f, v)
            if problem:
                add(f"{gp}.{key}", "invalid_value", problem)


def _check_date_range(f: SpecField, gen: SpecSeedGenerator, gp: str, rows: int, m: Any, add: Add) -> None:
    lo, hi = _iso_date(gen.min), _iso_date(gen.max)
    if lo is None or hi is None:
        add(gp, "required", "date_range needs min and max dates like 2026-01-31")
        return
    if lo > hi:
        add(f"{gp}.min", "invalid_range", "min is after max")
    elif not (1990 <= lo.year and hi.year <= 2100):
        add(gp, "invalid_value", "years 1990 to 2100 only")


def _check_bool_ratio(f: SpecField, gen: SpecSeedGenerator, gp: str, rows: int, m: Any, add: Add) -> None:
    if gen.ratio is None or isinstance(gen.ratio, bool) or not 0 <= gen.ratio <= 1:
        add(f"{gp}.ratio", "invalid_value", "ratio must be a number from 0 to 1")


def _check_words(f: SpecField, gen: SpecSeedGenerator, gp: str, rows: int, m: Any, add: Add) -> None:
    lo, hi = gen.min_words, gen.max_words
    if lo is None or hi is None or not 1 <= lo <= hi <= MAX_WORDS:
        add(gp, "invalid_value", f"words needs 1 <= min_words <= max_words <= {MAX_WORDS}")
        return
    longest = hi * MAX_WORD_LENGTH + (hi - 1)
    if f.max_length is not None and longest > f.max_length:
        add(f"{gp}.max_words", "too_long", f"up to {longest} characters do not fit max_length {f.max_length}")


def _check_email(f: SpecField, gen: SpecSeedGenerator, gp: str, rows: int, m: Any, add: Add) -> None:
    prefix = gen.prefix if gen.prefix is not None else "user"
    if not EMAIL_PREFIX_RE.fullmatch(prefix):
        add(f"{gp}.prefix", "invalid_value", "prefix: lowercase letters and digits (max 20)")
        return
    longest = len(email_text(prefix, max(rows - 1, 0)))
    if f.max_length is not None and longest > f.max_length:
        add(f"{gp}.prefix", "too_long", f"values up to {longest} characters do not fit max_length {f.max_length}")


def _check_state(f: SpecField, gen: SpecSeedGenerator, gp: str, rows: int, machine: Any, add: Add) -> None:
    weights = gen.weights
    if not weights:
        add(f"{gp}.weights", "required", "state needs a weight for at least one state")
        return
    states = set(f.enum_values or [])
    reachable = reachable_states(
        {
            "initial": machine.initial,
            "states": sorted(states),
            "transitions": [
                {"name": t.name, "from": t.from_states, "to": t.to_state, "auto": t.auto}
                for t in machine.transitions
            ],
        }
    )
    for state, weight in sorted(weights.items()):
        wp = f"{gp}.weights.{state}"
        if state not in states:
            add(wp, "unknown_state", f"{state!r} is not a state")
        elif isinstance(weight, bool) or not 0 <= weight <= 1000:
            add(wp, "invalid_value", "a weight is a whole number from 0 to 1000")
        elif weight > 0 and state not in reachable:
            add(wp, "unreachable_state", f"no chain of transitions leads from {machine.initial!r} to {state!r}")
    if not any(isinstance(w, int) and w > 0 for w in weights.values()):
        add(f"{gp}.weights", "invalid_value", "give at least one state a weight above 0")


_CHECKS: dict[str, Callable[..., None]] = {
    "constant": _check_constant,
    "one_of": _check_one_of,
    "sequence": _check_sequence,
    "int_range": _check_int_range,
    "decimal_range": _check_decimal_range,
    "date_range": _check_date_range,
    "bool_ratio": _check_bool_ratio,
    "words": _check_words,
    "email": _check_email,
    "state": _check_state,
}


def _check_reference(
    spec: Spec,
    prof: SpecSeedProfile,
    pe: SpecSeedEntity,
    gen: SpecSeedGenerator,
    fk: tuple[str, bool, bool],
    fp: str,
    plan: dict[str, SpecSeedEntity],
    scoped_names: set[str],
    add: Add,
) -> None:
    gp = f"{fp}.generator"
    target, required, unique = fk
    if gen.type != "reference":
        add(f"{gp}.type", "type_mismatch", "a foreign key column takes the reference generator")
        return
    _check_keys(gen, GENERATORS["reference"][1], gp, add)
    if gen.entity != target:
        add(f"{gp}.entity", "type_mismatch", f"this foreign key points at {target}, not {gen.entity!r}")
        return
    if target == pe.entity:
        add(f"{gp}.entity", "self_reference", "an entity cannot reference its own rows in a seed plan")
        return
    parent = plan.get(target)
    if parent is None:
        add(f"{gp}.entity", "reference_not_seeded", f"{target} has no plan in this profile: seed it too")
        return
    pick = gen.pick or "cycle"
    if pick not in ("cycle", "random"):
        add(f"{gp}.pick", "invalid_value", "pick is cycle or random")
        return
    if parent.count < 1 and required:
        add(f"{gp}.entity", "empty_reference", f"{target} has count 0, so {pe.entity} has nothing to point at")
    if pe.entity not in scoped_names and target in scoped_names:
        add(
            f"{gp}.entity",
            "tenant_mismatch",
            f"{pe.entity} is shared by all tenants but {target} belongs to a tenant",
        )
    if unique:
        if pick != "cycle":
            add(f"{gp}.pick", "unique_not_injective", "a one_to_one reference must use pick: cycle")
        else:
            tenants = prof.tenants if prof.tenants > 0 else 1
            mine = pe.count * (tenants if pe.entity in scoped_names else 1)
            theirs = parent.count * (tenants if target in scoped_names else 1)
            if mine > theirs:
                add(f"{gp}.entity", "unique_not_injective", f"{mine} rows cannot each get their own {target} ({theirs})")


def _check_reference_cycles(prof: SpecSeedProfile, p: str, add: Add) -> None:
    edges: dict[str, set[str]] = {}
    for pe in prof.entities:
        for sf in pe.fields:
            if sf.generator.type == "reference" and sf.generator.entity:
                edges.setdefault(pe.entity, set()).add(sf.generator.entity)
    state: dict[str, int] = {}

    def visit(node: str) -> bool:
        if state.get(node) == 1:
            return True
        if state.get(node) == 2:
            return False
        state[node] = 1
        if any(visit(n) for n in sorted(edges.get(node, ())) if n != node):
            return True
        state[node] = 2
        return False

    if any(visit(n) for n in sorted(edges)):
        add(f"{p}.entities", "reference_cycle", "the references between seeded entities form a loop")
