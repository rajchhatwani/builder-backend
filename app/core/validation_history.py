"""Validation for the `history` section (change history). Issues go through `add(path, code, message)`.
Nothing here evaluates anything: names are checked against the entity's own fields."""

from collections.abc import Callable

from app.core.spec_models import Spec, SpecEntity
from app.core.validation_runtime import looks_secret

Add = Callable[[str, str, str], None]

CH_TABLES = ("ch_changes",)
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 3650
# Cap for every stored old/new value (bytes of its JSON text); longer values are cut with a marker.
MAX_VALUE_BYTES = 4096


def history_active(spec: Spec) -> bool:
    return bool(spec.history)


def check_history(spec: Spec, entities: dict[str, SpecEntity], add: Add) -> None:
    auth_on = spec.auth is not None and spec.auth.enabled
    roles = {r.name for r in spec.auth.roles} if spec.auth is not None else set()
    machine_fields = {(m.entity, m.field) for m in spec.state_machines}
    seen: set[str] = set()
    for i, h in enumerate(spec.history):
        p = f"history[{i}]"
        entity = entities.get(h.entity)
        if entity is None:
            add(f"{p}.entity", "unknown_entity", f"no entity named {h.entity!r}")
        elif h.entity in seen:
            add(f"{p}.entity", "duplicate", f"{h.entity} already has a history config")
        seen.add(h.entity)
        if not MIN_RETENTION_DAYS <= h.retention_days <= MAX_RETENTION_DAYS:
            add(
                f"{p}.retention_days",
                "invalid_value",
                f"retention_days must be {MIN_RETENTION_DAYS} to {MAX_RETENTION_DAYS}",
            )
        if not h.fields:
            add(f"{p}.fields", "required", "name at least one field to record")
        names = {f.name for f in entity.fields} if entity is not None else set()
        listed: set[str] = set()
        for k, name in enumerate(h.fields):
            fp = f"{p}.fields[{k}]"
            if name in listed:
                add(fp, "duplicate_name", f"field {name} is listed twice")
                continue
            listed.add(name)
            if looks_secret(name):
                add(fp, "secret_name", "history is readable by roles and kept: never record secrets")
            elif entity is not None and name not in names:
                add(fp, "unknown_field", f"{h.entity} has no field named {name!r}")
            elif (h.entity, name) in machine_fields:
                add(fp, "state_field", "the state of a state machine is already logged in its state history")
        if h.view_roles and not auth_on:
            add(f"{p}.view_roles", "auth_required", "roles need the auth feature switched on")
        elif auth_on:
            for k, role in enumerate(h.view_roles):
                if role not in roles:
                    add(f"{p}.view_roles[{k}]", "unknown_role", f"no role named {role!r}")
