"""Validation for the `notifications` section (templates, preferences, delivery log over the provider
adapters). Issues go through `add(path, code, message)`. Fail closed: every type needs a template for
each of its channels, template text may only use declared `{{ variables }}` (no expressions), and
nothing that looks like a credential is accepted."""

import re
from collections.abc import Callable

from app.core.spec_models import Spec, SpecEntity, SpecNotificationType
from app.core.validation_events import events_active
from app.core.validation_providers import providers_active, secret_value
from app.core.validation_runtime import looks_secret

Add = Callable[[str, str, str], None]

NOTIFICATION_TABLES = ("nt_deliveries", "nt_preferences", "nt_templates")
CHANNELS = ("email", "sms", "push")
CATEGORIES = ("transactional", "optional")
EVENT_OPS = ("created", "updated", "deleted")
NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")
VARIABLE_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")
PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z][a-z0-9_]{0,39})\s*\}\}")
FIELD_RE = re.compile(r"[a-z_][a-z0-9_]{0,62}")
MAX_TYPES = 100
MAX_VARIABLES = 30
MAX_SUBJECT = 200
MAX_BODY = {"email": 20_000, "sms": 1_000, "push": 1_000}
MAX_RETENTION_DAYS = 3650


def notifications_active(spec: Spec) -> bool:
    return spec.notifications is not None and spec.notifications.enabled


def template_problem(text: str, variables: set[str]) -> str | None:
    """Why `text` cannot be a template, or None. Only `{{ name }}` of a declared variable is allowed:
    any other brace sequence (`{{ 7*7 }}`, `{% ... %}`, `{{ a.b }}`, a stray `}}`) is refused."""
    unknown = sorted({m.group(1) for m in PLACEHOLDER_RE.finditer(text)} - variables)
    if unknown:
        return f"unknown variable(s): {', '.join(unknown)}"
    rest = PLACEHOLDER_RE.sub("", text)
    if any(token in rest for token in ("{{", "}}", "{%", "%}", "{#", "#}")):
        return "only {{ name }} placeholders of declared variables are allowed (no expressions, filters or blocks)"
    return None


def _event_entity(event: str, spec: Spec) -> tuple[SpecEntity | None, str]:
    """The entity and operation of an event name like `leave_request.created`."""
    prefix, _, op = event.partition(".")
    for entity in spec.entities:
        if re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", entity.name).lower() == prefix:
            return entity, op
    return None, op


def _data_fields(entity: SpecEntity, spec: Spec) -> set[str]:
    names = {"id"} | {f.name for f in entity.fields if f.type != "json"}
    for rel in spec.relations:
        if rel.kind == "one_to_many" and rel.to_entity == entity.name:
            names.add(f"{rel.to_name}_id")
    return names


def check_notifications(spec: Spec, add: Add) -> None:
    nf = spec.notifications
    if nf is None or not nf.enabled:
        return
    if spec.auth is None or not spec.auth.enabled:
        add("notifications", "needs_auth", "preferences and templates are per user and per tenant: enable auth first")
    else:
        roles = {r.name for r in spec.auth.roles}
        if nf.admin_role not in roles:
            add("notifications.admin_role", "unknown_role", f"admin_role {nf.admin_role!r} is not a role of the project")
    if not providers_active(spec):
        add("notifications", "needs_providers", "messages are sent through the provider adapters: enable providers first")
    if not nf.types:
        add("notifications.types", "no_types", "declare at least one notification type")
    if len(nf.types) > MAX_TYPES:
        add("notifications.types", "too_many", f"at most {MAX_TYPES} types")
    if isinstance(nf.max_attempts, bool) or not 1 <= nf.max_attempts <= 10:
        add("notifications.max_attempts", "invalid_value", "max_attempts must be 1 to 10")
    if isinstance(nf.backoff_seconds, bool) or not 1 <= nf.backoff_seconds <= 3600:
        add("notifications.backoff_seconds", "invalid_value", "backoff_seconds must be 1 to 3600")
    if isinstance(nf.retention_days, bool) or not 1 <= nf.retention_days <= MAX_RETENTION_DAYS:
        add("notifications.retention_days", "invalid_value", f"retention_days must be 1 to {MAX_RETENTION_DAYS}")

    seen: set[str] = set()
    for i, t in enumerate(nf.types):
        path = f"notifications.types[{i}]"
        if not NAME_RE.fullmatch(t.name):
            add(f"{path}.name", "invalid_name", "a type name is lowercase letters, digits and underscores (40 at most)")
        elif t.name in seen:
            add(f"{path}.name", "duplicate_name", f"notification type {t.name!r} is declared twice")
        seen.add(t.name)
        if t.category not in CATEGORIES:
            add(f"{path}.category", "invalid_value", f"category must be one of: {', '.join(CATEGORIES)}")
        if not t.channels:
            add(f"{path}.channels", "no_channels", "a type needs at least one channel")
        if len(set(t.channels)) != len(t.channels):
            add(f"{path}.channels", "duplicate_channel", "a channel is listed twice")
        for c in t.channels:
            if c not in CHANNELS:
                add(f"{path}.channels", "unknown_channel", f"channel {c!r} must be one of: {', '.join(CHANNELS)}")
        if len(t.variables) > MAX_VARIABLES:
            add(f"{path}.variables", "too_many", f"at most {MAX_VARIABLES} variables")
        if len(set(t.variables)) != len(t.variables):
            add(f"{path}.variables", "duplicate_variable", "a variable is declared twice")
        for v in t.variables:
            if not VARIABLE_RE.fullmatch(v):
                add(f"{path}.variables", "invalid_name", f"variable {v!r}: lowercase letters, digits and underscores")
            elif looks_secret(v):
                add(f"{path}.variables", "secret_in_spec", f"variable {v!r} looks like a credential: messages must not carry secrets")
        _check_templates(t, path, add)
        _check_event(spec, t, path, add)


def _check_templates(t: SpecNotificationType, path: str, add: Add) -> None:
    variables = set(t.variables)
    have: set[str] = set()
    for j, tpl in enumerate(t.templates):
        tp = f"{path}.templates[{j}]"
        if tpl.channel not in t.channels:
            add(f"{tp}.channel", "unknown_channel", f"channel {tpl.channel!r} is not a channel of this type")
            continue
        if tpl.channel in have:
            add(f"{tp}.channel", "duplicate_channel", f"two templates for {tpl.channel!r}")
        have.add(tpl.channel)
        if tpl.html and tpl.channel != "email":
            add(f"{tp}.html", "invalid_value", "html applies to email only")
        if not tpl.body.strip():
            add(f"{tp}.body", "empty_template", "the body must not be empty")
        if len(tpl.body) > MAX_BODY.get(tpl.channel, 1_000):
            add(f"{tp}.body", "too_long", f"at most {MAX_BODY.get(tpl.channel, 1_000)} characters")
        if len(tpl.subject) > MAX_SUBJECT:
            add(f"{tp}.subject", "too_long", f"at most {MAX_SUBJECT} characters")
        if "\0" in tpl.body:
            add(f"{tp}.body", "invalid_value", "a template must not contain a NUL character")
        if any(ch in tpl.subject for ch in "\r\n\0"):
            add(f"{tp}.subject", "invalid_value", "a subject is one line: no line breaks")
        if tpl.channel in ("email", "push") and not tpl.subject.strip():
            add(f"{tp}.subject", "empty_template", "email and push need a subject / title")
        if tpl.channel == "sms" and tpl.subject:
            add(f"{tp}.subject", "invalid_value", "an SMS has no subject")
        for field_name, text in (("subject", tpl.subject), ("body", tpl.body)):
            problem = template_problem(text, variables)
            if problem is not None:
                add(f"{tp}.{field_name}", "invalid_template", problem)
            if secret_value(text):
                add(f"{tp}.{field_name}", "secret_in_spec", "this text looks like a credential")
    for c in t.channels:
        if c in CHANNELS and c not in have:
            add(f"{path}.templates", "missing_template", f"no default template for channel {c!r}")


def _check_event(spec: Spec, t: SpecNotificationType, path: str, add: Add) -> None:
    if t.on_event is None:
        if t.recipient_key_field is not None or t.address_fields:
            add(f"{path}.on_event", "missing_event", "recipient fields are set but no on_event is")
        return
    if not events_active(spec):
        add(f"{path}.on_event", "needs_events", "triggering on events needs the events block")
        return
    entity, op = _event_entity(t.on_event, spec)
    if entity is None or op not in EVENT_OPS:
        add(f"{path}.on_event", "unknown_event", "on_event is `<entity>.created|updated|deleted`, e.g. order.created")
        return
    allowed = _data_fields(entity, spec)
    key = t.recipient_key_field
    if key is None:
        add(f"{path}.recipient_key_field", "missing_field", "name the event-data field that identifies the recipient")
    elif key not in allowed or looks_secret(key):
        add(f"{path}.recipient_key_field", "unknown_field", f"{key!r} is not a published field of {entity.name}")
    for channel, field_name in t.address_fields.items():
        if channel not in t.channels:
            add(f"{path}.address_fields.{channel}", "unknown_channel", "not a channel of this type")
        elif field_name not in allowed or looks_secret(field_name) or not FIELD_RE.fullmatch(field_name):
            add(f"{path}.address_fields.{channel}", "unknown_field", f"{field_name!r} is not a published field of {entity.name}")
    for c in t.channels:
        if c not in t.address_fields:
            add(f"{path}.address_fields", "missing_address_field", f"no address field for channel {c!r}")
