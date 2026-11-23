"""Validation for the `compliance` block (retention + legal hold D42, consent D44, break-glass D45, de-identified
export D46). Issues go through `add(path, code, message)`. Nothing here purges or exports anything.

The treatment `keep` is refused on a direct identifier (a field named like an email, phone, name, ssn, passport,
address, birth date, postcode / zip, mrn, ip or location, a free-text field, or a field that regulated mode protects). A protected field can only be hashed or dropped in an
export: its clear text never leaves the database through the compliance routes."""

import re
from collections.abc import Callable

from app.core.spec_models import Spec, SpecEntity
from app.core.validation_regulated import regulated_active

Add = Callable[[str, str, str], None]

MAX_RULES = 64
MAX_PURPOSES = 32
PURPOSE_SLUG = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
IDENTIFIER_FRAGMENTS = (
    "email", "phone", "name", "ssn", "passport", "address", "dob", "birth", "postal", "postcode",
    "latitude", "longitude", "licence", "license", "insurance",
)
# short names match a whole word only (`ip` must not match `description`)
IDENTIFIER_WORDS = ("ip", "zip", "mrn", "lat", "lng", "lon", "geo", "nhs", "tin", "nin", "dob", "ssn")
IDENTIFIER_TYPES = ("email", "phone", "text")  # free text can hold anything: never `keep`
DATE_TYPES = ("date", "datetime")
BUILTIN_DATES = ("created_at", "updated_at")
TEXT_TYPES = ("string", "text")


def compliance_active(spec: Spec) -> bool:
    return spec.compliance is not None and spec.compliance.enabled


def is_direct_identifier(name: str, field_type: str | None) -> bool:
    lowered = name.lower()
    words = {w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", name)}
    return (
        field_type in IDENTIFIER_TYPES
        or any(fragment in lowered for fragment in IDENTIFIER_FRAGMENTS)
        or any(word in words for word in IDENTIFIER_WORDS)
    )


def _fk_columns(spec: Spec, entity: str) -> set[str]:
    """Columns another entity's relation adds to `entity` (the many side of a one-to-many / the to side of a one-to-one)."""
    return {f"{r.to_name}_id" for r in spec.relations if r.to_entity == entity and r.kind in ("one_to_many", "one_to_one")}


def check_compliance(spec: Spec, entities: dict[str, SpecEntity], add: Add) -> None:
    block = spec.compliance
    if block is None:
        return
    protected = (
        {(f.entity, f.field) for f in spec.regulated.fields}  # type: ignore[union-attr]
        if regulated_active(spec)
        else set()
    )
    if block.enabled:
        if spec.auth is None:
            add("compliance", "compliance_needs_auth", "compliance needs auth (its routes are for signed-in administrators)")
        if not block.roles:
            add("compliance.roles", "compliance_needs_roles", "name at least one role that may administer compliance (default deny)")
    known_roles = {r.name for r in spec.auth.roles} if spec.auth is not None else set()
    if spec.auth is not None:
        for i, role in enumerate(block.roles):
            if role not in known_roles:
                add(f"compliance.roles[{i}]", "unknown_role", f"no auth role named {role!r}")
    if len(block.retention) > MAX_RULES or len(block.export_fields) > MAX_RULES * 4:
        add("compliance", "too_many", "too many retention rules or export fields")

    # retention
    seen_rules: set[tuple[str, str]] = set()
    for i, rule in enumerate(block.retention):
        path = f"compliance.retention[{i}]"
        entity = entities.get(rule.entity)
        if entity is None:
            add(f"{path}.entity", "unknown_entity", f"no entity named {rule.entity!r}")
            continue
        if (rule.entity, rule.action) in seen_rules:
            add(path, "duplicate_rule", f"{rule.entity} has two {rule.action} rules")
        seen_rules.add((rule.entity, rule.action))
        by_name = {f.name: f for f in entity.fields}
        if rule.date_field not in BUILTIN_DATES:
            date_field = by_name.get(rule.date_field)
            if date_field is None:
                add(f"{path}.date_field", "unknown_field", f"{rule.entity} has no field named {rule.date_field!r}")
            elif date_field.type not in DATE_TYPES:
                add(f"{path}.date_field", "retention_bad_date_field",
                    f"{rule.entity}.{rule.date_field} is {date_field.type}: the retention clock needs a date or datetime")
        if rule.action == "anonymise" and not rule.anonymise_fields:
            add(f"{path}.anonymise_fields", "retention_anonymise_empty", "action anonymise needs at least one field to clear")
        for j, name in enumerate(rule.anonymise_fields):
            field = by_name.get(name)
            if field is None:
                add(f"{path}.anonymise_fields[{j}]", "unknown_field", f"{rule.entity} has no field named {name!r}")
            elif field.required and field.type not in TEXT_TYPES:
                add(f"{path}.anonymise_fields[{j}]", "retention_anonymise_type",
                    f"{rule.entity}.{name} is required and {field.type}: it cannot be cleared (only optional fields or text can)")

    # consent purposes
    if len(block.consent_purposes) > MAX_PURPOSES:
        add("compliance.consent_purposes", "too_many", f"at most {MAX_PURPOSES} purposes")
    seen_purposes: set[str] = set()
    for i, purpose in enumerate(block.consent_purposes):
        if not PURPOSE_SLUG.match(purpose):
            add(f"compliance.consent_purposes[{i}]", "invalid_purpose", f"{purpose!r} is not a slug (lowercase letters, digits, - _)")
        elif purpose in seen_purposes:
            add(f"compliance.consent_purposes[{i}]", "duplicate_purpose", f"purpose {purpose!r} is listed twice")
        seen_purposes.add(purpose)

    # break-glass
    bg = block.break_glass
    if bg.enabled:
        if spec.auth is None:
            add("compliance.break_glass", "compliance_needs_auth", "break-glass needs auth")
        if not bg.roles:
            add("compliance.break_glass.roles", "break_glass_needs_roles", "break-glass needs at least one role that may ask for it")
    if spec.auth is not None:
        for i, role in enumerate(bg.roles):
            if role not in known_roles:
                add(f"compliance.break_glass.roles[{i}]", "unknown_role", f"no auth role named {role!r}")

    # export
    export_entities = {x.entity for x in block.export_entities}
    for i, ee in enumerate(block.export_entities):
        path = f"compliance.export_entities[{i}]"
        entity = entities.get(ee.entity)
        if entity is None:
            add(f"{path}.entity", "unknown_entity", f"no entity named {ee.entity!r}")
            continue
        if ee.subject_field is not None:
            valid = {f.name for f in entity.fields} | {"id"} | _fk_columns(spec, ee.entity)
            if ee.subject_field not in valid:
                add(f"{path}.subject_field", "unknown_field", f"{ee.entity} has no field named {ee.subject_field!r}")
        elif block.export_consent_purpose is not None:
            add(f"{path}.subject_field", "export_needs_subject",
                "an export gated by consent needs the field that holds the subject of each row")
    for i, ef in enumerate(block.export_fields):
        path = f"compliance.export_fields[{i}]"
        entity = entities.get(ef.entity)
        if entity is None:
            add(f"{path}.entity", "unknown_entity", f"no entity named {ef.entity!r}")
            continue
        if ef.entity not in export_entities:
            add(f"{path}.entity", "export_entity_not_listed", f"{ef.entity} is not in export_entities")
        field = next((f for f in entity.fields if f.name == ef.field), None)
        if field is None and ef.field not in BUILTIN_DATES:
            add(f"{path}.field", "unknown_field", f"{ef.entity} has no field named {ef.field!r}")
            continue
        field_type = field.type if field is not None else "datetime"
        if (ef.entity, ef.field) in protected:
            if ef.treatment in ("keep", "generalise"):
                add(f"{path}.treatment", "export_keep_identifier",
                    f"{ef.entity}.{ef.field} is protected (regulated): an export can only hash or drop it")
        elif ef.treatment == "keep" and is_direct_identifier(ef.field, field_type):
            add(f"{path}.treatment", "export_keep_identifier",
                f"{ef.entity}.{ef.field} is a direct identifier: use hash or drop, not keep")
    if block.export_consent_purpose is not None and block.export_consent_purpose not in seen_purposes:
        add("compliance.export_consent_purpose", "unknown_purpose",
            f"{block.export_consent_purpose!r} is not one of consent_purposes")
