"""Validation for the `documents` block (PDF templates).

Issues go through the `add(path, code, message)` callable that validation.validate passes in.
The template grammar lives in doc_engine (the module that ships into generated projects); this
module adds what only the builder knows: roles, entities, and the fields a bound template reads.
"""

import re
from collections.abc import Callable, Iterator
from typing import Any

from app.core import doc_engine as eng
from app.core.spec_models import Spec, SpecDocTemplate, SpecDocuments, SpecEntity

Add = Callable[[str, str, str], None]

ID_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")
MAX_TEMPLATES = 30
RATE_RE = re.compile(r"\d{1,6}/\d{0,3}(second|minute|hour|day)s?")
BUILTIN_ROW_FIELDS = {"id", "created_at", "updated_at", "created_by_id"}


def documents_active(spec: Spec) -> SpecDocuments | None:
    block = spec.documents
    return block if block is not None and block.enabled and block.templates else None


def check_documents(spec: Spec, add: Add) -> None:
    block = spec.documents
    if block is None or not block.enabled:
        return
    auth = spec.auth
    if block.templates and (auth is None or not auth.enabled):
        add(
            "documents",
            "documents.needs_auth",
            "documents are generated for signed-in people only (rendering costs CPU): switch "
            "authentication on first",
        )
    if not RATE_RE.fullmatch(block.rate_limit):
        add("documents.rate_limit", "invalid_value", "use a form like 30/minute")
    if len(block.templates) > MAX_TEMPLATES:
        add("documents.templates", "too_many", f"at most {MAX_TEMPLATES} templates")
    entities = {e.name: e for e in spec.entities}
    roles = {r.name for r in auth.roles} if auth is not None else set()
    seen: set[str] = set()
    for i, tpl in enumerate(block.templates):
        path = f"documents.templates[{i}]"
        if not ID_RE.fullmatch(tpl.id):
            add(
                f"{path}.id", "invalid_value", "lowercase letters, digits, _ (starts with a letter)"
            )
        elif tpl.id in seen:
            add(f"{path}.id", "duplicate", f"{tpl.id} is used twice")
        seen.add(tpl.id)
        if not tpl.roles:
            add(
                f"{path}.roles",
                "documents.no_roles",
                "choose who may render this template: an empty list means nobody",
            )
        for role in tpl.roles:
            if auth is not None and role not in roles:
                add(f"{path}.roles", "unknown_role", f"no role named {role}")
        for problem in eng.validate_template(tpl.template):
            add(f"{path}.template", "documents.template", problem)
        if tpl.compute is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", tpl.compute):
            add(f"{path}.compute", "invalid_value", "the name of a list in the data")
        if tpl.entity is not None:
            _check_entity(tpl, path, entities, add)


def _check_entity(
    tpl: SpecDocTemplate, path: str, entities: dict[str, SpecEntity], add: Add
) -> None:
    entity = entities.get(tpl.entity or "")
    if entity is None:
        add(f"{path}.entity", "unknown_entity", f"no entity named {tpl.entity}")
        return
    if "get" not in entity.options.operations:
        add(
            f"{path}.entity",
            "documents.entity_needs_get",
            f"{entity.name} must offer the get operation: it decides who may read a record",
        )
    fields = {f.name for f in entity.fields} | BUILTIN_ROW_FIELDS
    for where, text in _texts(tpl.template):
        for name, _ in eng.placeholders(text):
            parts = name.split(".")
            if parts[0] == "row" and len(parts) > 1 and parts[1] not in fields:
                add(
                    f"{path}.template",
                    "documents.unknown_field",
                    f"{where}: {entity.name} has no field {parts[1]!r}",
                )


def _texts(template: Any, where: str = "template") -> Iterator[tuple[str, str]]:
    """Every string in a template, with a short location, for placeholder checks."""
    if isinstance(template, str):
        yield where, template
    elif isinstance(template, dict):
        for key, value in template.items():
            if key != "data_base64":
                yield from _texts(value, f"{where}.{key}")
    elif isinstance(template, list):
        for i, value in enumerate(template):
            yield from _texts(value, f"{where}[{i}]")
