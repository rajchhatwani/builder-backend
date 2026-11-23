"""Validation for the `regulated` block (regulated mode D40, field encryption / tokenisation D41,
customer-managed keys D43). Issues go through `add(path, code, message)`. Nothing here encrypts anything.

A protected column holds ciphertext (or a token), so the database cannot compare, sort, search,
aggregate or index it. Every section that would do one of those on a protected field is refused with
`encrypted_field_used`. The only exception is an equality filter on a `searchable` field (blind index)."""

import re
from collections.abc import Callable

from app.core.metrics import MetricError, parse_metric
from app.core.spec_models import Spec, SpecEntity, SpecRegulatedField

Add = Callable[[str, str, str], None]

MAX_FIELDS = 64
PROTECTABLE_TYPES = ("string", "text")  # only text-like columns can hold ciphertext


def regulated_active(spec: Spec) -> bool:
    return spec.regulated is not None and spec.regulated.enabled


def _used(add: Add, path: str, entity: str, field: str, how: str) -> None:
    add(path, "encrypted_field_used", f"{entity}.{field} is protected (regulated): it cannot be used {how}")


def check_regulated(spec: Spec, entities: dict[str, SpecEntity], add: Add) -> None:
    block = spec.regulated
    if block is None:
        return
    if len(block.fields) > MAX_FIELDS:
        add("regulated.fields", "too_many", f"at most {MAX_FIELDS} protected fields")
    if block.enabled and block.key_provider == "env":
        add("regulated.key_provider", "regulated_needs_cmk",
            "an environment key is not customer-managed: use key_provider file or command")
    if block.enabled and spec.auth is None:
        add("regulated", "regulated_needs_auth", "regulated mode needs auth (protected data is for signed-in people)")
    seen: set[tuple[str, str]] = set()
    valid: dict[tuple[str, str], SpecRegulatedField] = {}
    for i, rf in enumerate(block.fields):
        path = f"regulated.fields[{i}]"
        entity = entities.get(rf.entity)
        if entity is None:
            add(f"{path}.entity", "unknown_entity", f"no entity named {rf.entity!r}")
            continue
        field = next((f for f in entity.fields if f.name == rf.field), None)
        if field is None:
            add(f"{path}.field", "unknown_field", f"{rf.entity} has no field named {rf.field!r}")
            continue
        if (rf.entity, rf.field) in seen:
            add(path, "duplicate_field", f"{rf.entity}.{rf.field} is listed twice")
            continue
        seen.add((rf.entity, rf.field))
        if field.type not in PROTECTABLE_TYPES:
            add(f"{path}.field", "type_not_supported", f"only string and text fields can be protected, not {field.type}")
            continue
        if field.unique or field.indexed:
            add(f"{path}.field", "encrypted_unique",
                f"{rf.entity}.{rf.field} is unique / indexed: ciphertext cannot be (use searchable for an equality lookup)")
        if rf.searchable and rf.mode != "encrypt":
            add(f"{path}.searchable", "searchable_needs_encrypt", "searchable (blind index) works with mode encrypt only")
        valid[(rf.entity, rf.field)] = rf
    if valid:
        _check_references(spec, entities, valid, add)


def _check_references(
    spec: Spec, entities: dict[str, SpecEntity], protected: dict[tuple[str, str], SpecRegulatedField], add: Add
) -> None:
    # entity options: sort / search need plaintext order or text; filter only as equality on a blind index.
    for e in spec.entities:
        for key in ("filterable", "sortable", "searchable"):
            for name in getattr(e.options, key):
                rf = protected.get((e.name, name))
                if rf is None:
                    continue
                if key == "filterable" and rf.searchable and rf.mode == "encrypt":
                    continue  # equality filter through <field>_bidx
                _used(add, f"entities[{e.name}].options.{key}", e.name, name, f"in options.{key}")
    # state machines: the guard `when` expressions read field values; the state field itself must be an enum.
    for i, m in enumerate(spec.state_machines):
        if (m.entity, m.field) in protected:
            _used(add, f"state_machines[{i}].field", m.entity, m.field, "as a state field")
        for j, t in enumerate(m.transitions):
            for (ent, fld) in protected:
                if ent == m.entity and t.when and re.search(rf"\b{re.escape(fld)}\b", t.when):
                    _used(add, f"state_machines[{i}].transitions[{j}].when", ent, fld, "in a guard expression")
    # numbering: a sequence writes plaintext numbers into its field.
    for i, q in enumerate(spec.sequences):
        if q.entity and q.field and (q.entity, q.field) in protected:
            _used(add, f"sequences[{i}].field", q.entity, q.field, "as a numbered field")
    # history records old / new values in a plaintext table.
    for i, h in enumerate(spec.history):
        for name in h.fields:
            if (h.entity, name) in protected:
                _used(add, f"history[{i}].fields", h.entity, name, "in a change history")
    # seed generators write plaintext columns.
    for i, prof in enumerate(spec.seed):
        for j, se in enumerate(prof.entities):
            for k, sf in enumerate(se.fields):
                if (se.entity, sf.field) in protected:
                    _used(add, f"seed[{i}].entities[{j}].fields[{k}]", se.entity, sf.field, "in a seed generator")
    # metrics: aggregates, filters and group-by run in SQL over the stored column.
    if spec.metrics_layer is not None:
        for i, raw in enumerate(spec.metrics_layer.definitions):
            try:
                d = parse_metric(raw)
            except MetricError:
                continue
            names = [d.field, d.group_by, *(f.field for f in d.filter)]
            for name in names:
                if name and (d.entity, name) in protected:
                    _used(add, f"metrics_layer.definitions[{i}]", d.entity, name, "in a metric")
    # document templates: a bound template reads `row.<field>` (plaintext is not available to the renderer).
    if spec.documents is not None:
        for i, tpl in enumerate(spec.documents.templates):
            if not tpl.entity:
                continue
            text = repr(tpl.template)
            for (ent, fld) in protected:
                if ent == tpl.entity and re.search(rf"row\.{re.escape(fld)}\b", text):
                    _used(add, f"documents.templates[{i}].template", ent, fld, "in a document template")
    # hooks: an input / output model field named like a protected field of the hook's entity.
    for i, hook in enumerate(spec.hooks):
        ent = hook.point.split(".", 1)[0]
        for side, model in (("input", hook.input), ("output", hook.output)):
            for k, hf in enumerate(model.fields):
                if (ent, hf.name) in protected:
                    _used(add, f"hooks[{i}].{side}.fields[{k}]", ent, hf.name, "in a hook field list")
    # agent entity_create actions: the proposal (a plaintext table) stores the payload the agent would insert.
    agents = spec.packs.ai.agents if spec.packs is not None and spec.packs.ai is not None else None
    if agents is not None:
        tables = {e.table_name: e.name for e in spec.entities}
        for i, action in enumerate(agents.actions):
            if action.kind != "entity_create" or action.entity not in tables:
                continue
            for name in action.fields:
                if (tables[action.entity], name) in protected:
                    _used(add, f"packs.ai.agents.actions[{i}].fields", tables[action.entity], name, "in an agent action")
    # spec.lists are value catalogues (statuses, categories) and ai pack doc fields are extraction slots:
    # neither names an entity field, so there is nothing to refuse.
