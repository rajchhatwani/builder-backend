"""Validation for the `hooks` section (custom logic under contract). Issues go through
`add(path, code, message)`. Nothing here imports or runs a hook: only names, types and limits are checked."""

import builtins
import datetime
import decimal
import keyword
import re
import uuid
from collections.abc import Callable

from pydantic import BaseModel

from app.core.validation_notifications import notifications_active
from app.core.validation_providers import providers_active
from app.core.validation_webhooks import webhooks_active
from app.core.spec_models import (
    Spec,
    SpecEntity,
    SpecHook,
    SpecHookField,
    SpecHookModel,
    SpecStateMachine,
)

Add = Callable[[str, str, str], None]

NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")
MODEL_RE = re.compile(r"[A-Z][A-Za-z0-9]{0,39}")
FIELD_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")
POINT_RE = re.compile(
    r"([A-Z][A-Za-z0-9_]*)\.(?:(before_save|validate|after_save|after_commit)"
    r"|transition_guard\(([a-z][a-z0-9_]*)\))"
)

MAX_HOOKS = 50
MAX_FIELDS = 30
MAX_FALLBACK_STRING = 500
KINDS = ("pure", "effect")
POLICIES = ("fail_closed", "fail_open", "fallback")
STAGES = ("before_save", "validate", "after_save", "after_commit")
HOOK_TYPES = ("string", "int", "float", "decimal", "bool", "date", "datetime", "uuid")

# Budget ceilings (per kind). outbound_calls stays 0 until the SDK has a declared-egress client.
CPU_MS_MIN = 1
CEILINGS = {
    "pure": {"cpu_ms": 1000, "rows": 0, "outbound_calls": 0},
    "effect": {"cpu_ms": 4000, "rows": 1000, "outbound_calls": 0},
}

# entity field type -> hook field type (other entity types cannot cross the contract)
ENTITY_TO_HOOK = {
    "string": "string",
    "text": "string",
    "enum": "string",
    "integer": "int",
    "bigint": "int",
    "float": "float",
    "decimal": "decimal",
    "boolean": "bool",
    "date": "date",
    "datetime": "datetime",
    "uuid": "uuid",
}

# Output shapes the platform acts on.
VALIDATE_OUTPUT = {"valid": ("bool", True), "message": ("string", False)}
GUARD_OUTPUT = {"allowed": ("bool", True), "reason": ("string", False)}

_RESERVED_MODEL_NAMES = frozenset(dir(builtins)) | {"BaseModel", "ConfigDict", "Field"}
_BASEMODEL_NAMES = frozenset(dir(BaseModel))


def ceilings_for(kind: str) -> dict[str, int]:
    return dict(CEILINGS[kind])


def hooks_active(spec: Spec) -> bool:
    return bool(spec.hooks)


def parse_point(point: str) -> tuple[str, str, str | None] | None:
    """(entity, stage, transition) for a legal point; transition is set only for transition_guard."""
    match = POINT_RE.fullmatch(point)
    if match is None:
        return None
    entity, stage, transition = match.groups()
    return entity, stage or "transition_guard", transition


def has_guard_hooks(spec: Spec) -> bool:
    return any((p := parse_point(h.point)) is not None and p[1] == "transition_guard" for h in spec.hooks)


def default_policy(hook: SpecHook) -> str:
    parsed = parse_point(hook.point)
    stage = parsed[1] if parsed else ""
    if stage in ("validate", "transition_guard"):
        return "fail_closed"
    if hook.kind == "effect" or stage == "after_commit":
        return "fail_open"
    return "fail_closed"


def policy_of(hook: SpecHook) -> str:
    return hook.failure_policy or default_policy(hook)


def check_hooks(spec: Spec, entities: dict[str, SpecEntity], add: Add) -> None:
    check_hook_effects_section(spec, add)
    if len(spec.hooks) > MAX_HOOKS:
        add("hooks", "too_many", f"at most {MAX_HOOKS} hooks")
        return
    machines = {m.entity: m for m in spec.state_machines}
    names: set[str] = set()
    models: set[str] = set()
    for i, hook in enumerate(spec.hooks):
        p = f"hooks[{i}]"
        if not NAME_RE.fullmatch(hook.name) or keyword.iskeyword(hook.name) or hook.name in dir(builtins):
            add(f"{p}.name", "invalid_value", "use lowercase letters, digits and '_' (max 40), not a Python name")
        elif hook.name in names:
            add(f"{p}.name", "duplicate_name", f"hook {hook.name} is listed twice")
        names.add(hook.name)
        entity, stage, transition = _check_point(spec, hook, entities, machines, p, add)
        _check_kind(hook, stage, p, add)
        in_fields = _check_model(hook.input, f"{p}.input", models, add)
        out_fields = _check_model(hook.output, f"{p}.output", models, add)
        if hook.input.name == hook.output.name:
            add(f"{p}.output.name", "duplicate_name", "input and output need different model names")
        if not in_fields:
            add(f"{p}.input.fields", "required", "the input model needs at least one field")
        if entity is not None:
            _check_input(entity, hook.input, f"{p}.input", add)
            _check_output(entity, stage, hook.output, machines, f"{p}.output", add)
        _check_policy(hook, stage, out_fields, p, add)
        _check_budget(hook, p, add)
        _check_reads(hook, entities, p, add)
        _check_effects(spec, hook, p, add)
        if transition is not None and entity is not None:
            _check_transition(hook, entity, transition, machines, p, add)


def _check_point(
    spec: Spec,
    hook: SpecHook,
    entities: dict[str, SpecEntity],
    machines: dict[str, SpecStateMachine],
    p: str,
    add: Add,
) -> tuple[SpecEntity | None, str, str | None]:
    parsed = parse_point(hook.point)
    if parsed is None:
        add(
            f"{p}.point",
            "invalid_value",
            "use <Entity>.before_save | validate | after_save | after_commit | transition_guard(<transition>)",
        )
        return None, "", None
    name, stage, transition = parsed
    entity = entities.get(name)
    if entity is None:
        add(f"{p}.point", "unknown_entity", f"no entity named {name!r}")
        return None, stage, transition
    if stage == "transition_guard" and name not in machines:
        add(f"{p}.point", "unknown_transition", f"{name} has no state machine")
    return entity, stage, transition


def _check_transition(
    hook: SpecHook,
    entity: SpecEntity,
    transition: str,
    machines: dict[str, SpecStateMachine],
    p: str,
    add: Add,
) -> None:
    machine = machines.get(entity.name)
    if machine is None:
        return
    found = next((t for t in machine.transitions if t.name == transition), None)
    if found is None:
        add(f"{p}.point", "unknown_transition", f"{entity.name} has no transition named {transition!r}")
    elif found.auto:
        add(f"{p}.point", "invalid_value", "a guard hook belongs to a manual transition, not an automatic one")


def _check_kind(hook: SpecHook, stage: str, p: str, add: Add) -> None:
    if hook.kind not in KINDS:
        add(f"{p}.kind", "invalid_value", f"kind must be one of {', '.join(KINDS)}")
    elif hook.kind == "effect" and stage and stage != "after_commit":
        add(f"{p}.kind", "invalid_value", "an effect hook may only run at after_commit")


def _check_model(model: SpecHookModel, p: str, models: set[str], add: Add) -> list[SpecHookField]:
    name = model.name
    if not MODEL_RE.fullmatch(name) or name in _RESERVED_MODEL_NAMES or keyword.iskeyword(name):
        add(f"{p}.name", "invalid_value", "use a CamelCase identifier (max 40) that is not a Python name")
    elif name in models:
        add(f"{p}.name", "duplicate_name", f"model {name} is used twice")
    models.add(name)
    if len(model.fields) > MAX_FIELDS:
        add(f"{p}.fields", "too_many", f"at most {MAX_FIELDS} fields")
        return []
    seen: set[str] = set()
    for k, f in enumerate(model.fields):
        fp = f"{p}.fields[{k}]"
        if (
            not FIELD_RE.fullmatch(f.name)
            or keyword.iskeyword(f.name)
            or f.name.startswith("model_")
            or f.name in _BASEMODEL_NAMES
        ):
            add(f"{fp}.name", "invalid_value", "use lowercase letters, digits and '_' (max 40), not a Python or Pydantic name")
        elif f.name in seen:
            add(f"{fp}.name", "duplicate_name", f"field {f.name} is listed twice")
        seen.add(f.name)
        if f.type not in HOOK_TYPES:
            add(f"{fp}.type", "invalid_value", f"type must be one of {', '.join(HOOK_TYPES)}")
    return list(model.fields)


def _entity_types(entity: SpecEntity) -> dict[str, str]:
    types = {f.name: ENTITY_TO_HOOK[f.type] for f in entity.fields if f.type in ENTITY_TO_HOOK}
    types["id"] = "uuid"
    return types


def _check_input(entity: SpecEntity, model: SpecHookModel, p: str, add: Add) -> None:
    types = _entity_types(entity)
    for k, f in enumerate(model.fields):
        fp = f"{p}.fields[{k}]"
        if f.name not in types:
            add(f"{fp}.name", "unknown_field", f"{entity.name} has no readable field named {f.name!r}")
        elif f.type in HOOK_TYPES and types[f.name] != f.type:
            add(f"{fp}.type", "type_mismatch", f"{entity.name}.{f.name} is {types[f.name]}, not {f.type}")


def _check_output(
    entity: SpecEntity,
    stage: str,
    model: SpecHookModel,
    machines: dict[str, SpecStateMachine],
    p: str,
    add: Add,
) -> None:
    fields = {f.name: f for f in model.fields}
    if stage == "validate" or stage == "transition_guard":
        shape = VALIDATE_OUTPUT if stage == "validate" else GUARD_OUTPUT
        for key, (kind, required) in shape.items():
            f = fields.get(key)
            if f is None:
                if required:
                    add(f"{p}.fields", "required", f"the output needs a required {kind} field {key!r}")
            elif f.type != kind or f.required != required:
                need = "required" if required else "optional"
                add(f"{p}.fields", "invalid_value", f"{key!r} must be an {need} {kind}")
        for k, f in enumerate(model.fields):
            if f.name not in shape:
                add(f"{p}.fields[{k}].name", "invalid_value", f"this output has only {', '.join(shape)}")
    elif stage == "before_save":
        types = _entity_types(entity)
        machine = machines.get(entity.name)
        state_field = machine.field if machine is not None else None
        if not model.fields:
            add(f"{p}.fields", "required", "a before_save hook returns at least one field to set")
        for k, f in enumerate(model.fields):
            fp = f"{p}.fields[{k}]"
            if f.name == "id" or f.name == state_field:
                add(f"{fp}.name", "invalid_value", f"{f.name} cannot be set by a hook")
            elif f.name not in types:
                add(f"{fp}.name", "unknown_field", f"{entity.name} has no settable field named {f.name!r}")
            elif f.type in HOOK_TYPES and types[f.name] != f.type:
                add(f"{fp}.type", "type_mismatch", f"{entity.name}.{f.name} is {types[f.name]}, not {f.type}")


def _check_policy(hook: SpecHook, stage: str, out_fields: list[SpecHookField], p: str, add: Add) -> None:
    policy = policy_of(hook)
    if policy not in POLICIES:
        add(f"{p}.failure_policy", "invalid_value", f"use one of {', '.join(POLICIES)}")
        return
    if stage in ("validate", "transition_guard") and policy != "fail_closed":
        add(f"{p}.failure_policy", "invalid_value", "guards and validation hooks must be fail_closed")
    if stage == "after_commit" and policy == "fail_closed":
        add(
            f"{p}.failure_policy",
            "invalid_value",
            "after_commit runs after the data is saved: it cannot be fail_closed (use fail_open or fallback)",
        )
    if policy != "fallback":
        if hook.fallback is not None:
            add(f"{p}.fallback", "invalid_value", "fallback values are only for the fallback policy")
        return
    if hook.fallback is None:
        add(f"{p}.fallback", "required", "the fallback policy needs fallback output values")
        return
    by_name = {f.name: f for f in out_fields}
    for key, value in hook.fallback.items():
        f = by_name.get(key)
        if f is None:
            add(f"{p}.fallback.{key}", "unknown_field", f"{key!r} is not an output field")
        elif not _value_fits(f.type, value):
            add(f"{p}.fallback.{key}", "invalid_value", f"not a valid {f.type}")
    for f in out_fields:
        if f.required and f.name not in hook.fallback:
            add(f"{p}.fallback", "required", f"the fallback must give a value for {f.name!r}")


def _value_fits(kind: str, value: object) -> bool:
    if kind == "string":
        return isinstance(value, str) and len(value) <= MAX_FALLBACK_STRING
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "float":
        return isinstance(value, int | float) and not isinstance(value, bool)
    try:
        if kind == "decimal":  # written as a string: "0.15"
            return isinstance(value, str) and decimal.Decimal(value).is_finite()
        if kind == "date":
            return isinstance(value, str) and bool(datetime.date.fromisoformat(value))
        if kind == "datetime":
            return isinstance(value, str) and bool(datetime.datetime.fromisoformat(value))
        if kind == "uuid":
            return isinstance(value, str) and bool(uuid.UUID(value))
    except (ValueError, ArithmeticError):
        return False
    return False


def _check_budget(hook: SpecHook, p: str, add: Add) -> None:
    ceiling = CEILINGS.get(hook.kind)
    if ceiling is None:
        return
    b = hook.budget
    if not CPU_MS_MIN <= b.cpu_ms <= ceiling["cpu_ms"]:
        add(f"{p}.budget.cpu_ms", "over_ceiling", f"cpu_ms must be {CPU_MS_MIN} to {ceiling['cpu_ms']} for a {hook.kind} hook")
    if not 0 <= b.rows <= ceiling["rows"]:
        add(f"{p}.budget.rows", "over_ceiling", f"rows must be 0 to {ceiling['rows']} for a {hook.kind} hook")
    if not 0 <= b.outbound_calls <= ceiling["outbound_calls"]:
        add(
            f"{p}.budget.outbound_calls",
            "over_ceiling",
            f"outbound_calls must be 0 to {ceiling['outbound_calls']} (no outbound client yet)",
        )


EFFECT_TYPES = ("email", "sms", "webhook", "notification")
HOST_RE = re.compile(r"[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?")


def _check_effects(spec: Spec, hook: SpecHook, p: str, add: Add) -> None:
    """The effectful tier (H2/H3, CO-3): off unless the project opts in, trusted authors only, fail closed."""
    fx = spec.hook_effects
    on = fx is not None and fx.enabled
    if hook.author not in (None, "trusted"):
        if hook.effects or on:
            add(f"{p}.author", "untrusted_author", "hooks by an AI agent or outside parties are not allowed when effects are on (no sandbox yet)")
        elif hook.author not in ("ai", "external"):
            add(f"{p}.author", "invalid_value", "author is trusted, ai or external")
    if hook.effect_budget is not None and not hook.effects:
        add(f"{p}.effect_budget", "invalid_value", "effect_budget needs a declared effects list")
    if not hook.effects:
        return
    if not on:
        add(f"{p}.effects", "effects_not_enabled", "effects are off: set hook_effects.enabled (trusted authors only)")
        return
    if hook.kind != "effect":
        add(f"{p}.effects", "invalid_value", "only an effect hook may declare effects")
    seen: set[str] = set()
    for k, name in enumerate(hook.effects):
        ep = f"{p}.effects[{k}]"
        if name not in EFFECT_TYPES:
            add(ep, "invalid_value", f"effect must be one of {', '.join(EFFECT_TYPES)}")
        elif name in seen:
            add(ep, "duplicate_name", f"{name} is listed twice")
        seen.add(name)
        if name in ("email", "sms") and not providers_active(spec):
            add(ep, "needs_providers", f"{name} goes through the provider framework: enable providers")
        if name == "webhook" and not webhooks_active(spec):
            add(ep, "needs_webhooks", "webhook effects use the webhook egress guard: enable webhooks")
        if name == "notification" and not notifications_active(spec):
            add(ep, "needs_notifications", "notification effects need notifications enabled")
    if "webhook" in seen and fx is not None and not fx.webhook_hosts:
        add("hook_effects.webhook_hosts", "required", "a webhook effect needs an allow-list of hosts")
    eb = hook.effect_budget
    if eb is not None:
        if not 1 <= eb.calls_per_effect <= 20:
            add(f"{p}.effect_budget.calls_per_effect", "over_ceiling", "calls_per_effect must be 1 to 20")
        if not 1 <= eb.payload_bytes <= 262144:
            add(f"{p}.effect_budget.payload_bytes", "over_ceiling", "payload_bytes must be 1 to 262144")
        if not 1 <= eb.outbound_per_minute <= 600:
            add(f"{p}.effect_budget.outbound_per_minute", "over_ceiling", "outbound_per_minute must be 1 to 600")


def check_hook_effects_section(spec: Spec, add: Add) -> None:
    fx = spec.hook_effects
    if fx is None:
        return
    if fx.enabled and not fx.trusted_authors_only:
        add("hook_effects.trusted_authors_only", "required", "effectful hooks need the owner's confirmation: trusted_authors_only must be true")
    if fx.enabled and not spec.hooks:
        add("hook_effects", "invalid_value", "hook_effects needs at least one hook")
    for k, host in enumerate(fx.webhook_hosts):
        if not HOST_RE.fullmatch(host) or host.replace(".", "").isdigit():
            add(f"hook_effects.webhook_hosts[{k}]", "invalid_value", "use a lowercase DNS host name (no IP address, scheme or port)")


def _check_reads(hook: SpecHook, entities: dict[str, SpecEntity], p: str, add: Add) -> None:
    seen: set[str] = set()
    for k, name in enumerate(hook.reads):
        if name not in entities:
            add(f"{p}.reads[{k}]", "unknown_entity", f"no entity named {name!r}")
        elif name in seen:
            add(f"{p}.reads[{k}]", "duplicate_name", f"{name} is listed twice")
        seen.add(name)
    if hook.reads and hook.kind != "effect":
        add(f"{p}.reads", "invalid_value", "only an effect hook may read through the SDK")
    if hook.reads and hook.budget.rows <= 0:
        add(f"{p}.budget.rows", "required", "reading needs a rows budget above 0")
    if not hook.reads and hook.budget.rows > 0:
        add(f"{p}.reads", "required", "a rows budget needs the entities the hook may read")
