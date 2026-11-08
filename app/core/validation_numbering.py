"""Validation of numbered fields: a sequence with `entity` and `field` set numbers that field.

The platform draws the next number from the sequence INSIDE the transaction that inserts the row, so a
rolled-back create burns nothing and parallel creates get distinct numbers. The field is therefore
owned by the platform: callers can neither set nor change it. Issues go through `add(path, code, message)`.
"""

from collections.abc import Callable

from app.core.spec_models import Spec, SpecEntity, SpecField, SpecSequence

Add = Callable[[str, str, str], None]

STRING_FALLBACK_LENGTH = 255  # same default as the generator's string column
YEAR_PART = 5  # "2026-"
COUNTER_DIGITS = 9  # the counter may grow to a billion before the text could outgrow the column


def numbering(spec: Spec) -> dict[tuple[str, str], str]:
    """(entity, field) -> sequence name, for every sequence that numbers a field."""
    return {
        (q.entity, q.field): q.name
        for q in spec.sequences
        if q.entity is not None and q.field is not None
    }


def is_numeric_sequence(q: SpecSequence) -> bool:
    """A bare counter (no prefix, no year, no padding) can be stored in a bigint column."""
    return q.prefix == "" and not q.reset_yearly and q.padding == 0


def longest_number(q: SpecSequence) -> int:
    return len(q.prefix) + (YEAR_PART if q.reset_yearly else 0) + max(q.padding, COUNTER_DIGITS)


def check_numbered_fields(spec: Spec, entities: dict[str, SpecEntity], add: Add) -> None:
    machines = {m.entity: m.field for m in spec.state_machines}
    bound: dict[tuple[str, str], str] = {}
    for i, q in enumerate(spec.sequences):
        p = f"sequences[{i}]"
        if q.entity is None and q.field is None:
            continue
        if q.entity is None or q.field is None:
            add(p, "sequence_binding", "set both entity and field to number a field, or neither")
            continue
        entity = entities.get(q.entity)
        if entity is None:
            add(f"{p}.entity", "unknown_entity", f"no entity named {q.entity!r}")
            continue
        field = next((f for f in entity.fields if f.name == q.field), None)
        if field is None:
            add(f"{p}.field", "unknown_field", f"{q.entity} has no field named {q.field!r}")
            continue
        where = f"{q.entity}.{q.field}"
        if (q.entity, q.field) in bound:
            add(
                p,
                "field_in_use",
                f"{where} is already numbered by sequence {bound[(q.entity, q.field)]!r}",
            )
        bound[(q.entity, q.field)] = q.name
        if machines.get(q.entity) == q.field:
            add(
                p,
                "sequence_field",
                f"{where} is the state of a state machine: it cannot be numbered",
            )
        _check_field(field, q, where, p, add)


def _check_field(f: SpecField, q: SpecSequence, where: str, p: str, add: Add) -> None:
    if f.type == "string":
        limit = f.max_length or STRING_FALLBACK_LENGTH
        if limit < longest_number(q):
            add(
                f"{p}.field",
                "sequence_field",
                f"{where} holds at most {limit} characters but numbers of {q.name} can reach "
                f"{longest_number(q)}: raise max_length",
            )
    elif f.type == "bigint":
        if not is_numeric_sequence(q):
            add(
                f"{p}.field",
                "sequence_field",
                f"{where} is a number but sequence {q.name} has a prefix, a year or padding: "
                "use a string field",
            )
    else:
        add(
            f"{p}.field",
            "sequence_field",
            f"{where} must be a string (or a bigint for a bare counter), not {f.type}",
        )
    if not f.unique:
        add(f"{p}.field", "sequence_field", f"{where} must be unique: a number is handed out once")
    if not f.required:
        add(f"{p}.field", "sequence_field", f"{where} must be required: every row gets a number")
    if f.default is not None:
        add(
            f"{p}.field",
            "sequence_field",
            f"{where} cannot have a default: the platform assigns the value",
        )
    if q.per_tenant:
        # `unique` is table-wide: two tenants would both get number 1 and the second insert would fail.
        add(
            f"{p}.per_tenant",
            "per_tenant_unsupported",
            f"sequence {q.name} counts per tenant, but {where} is unique across the whole table, so "
            "tenants would collide on the same number: use a sequence that is not per_tenant",
        )
