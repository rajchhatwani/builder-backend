"""Validation for the `api_platform` block (public API keys D49, installable apps D50). Issues go through
`add(path, code, message)`. Default deny: nothing is readable through the public API unless an entity and the exact
fields are listed, and a field regulated mode protects (or anything that looks like a secret) is refused."""

import re
from collections.abc import Callable

from app.core.spec_models import Spec, SpecEntity
from app.core.validation_regulated import regulated_active

Add = Callable[[str, str, str], None]

LIMIT = re.compile(r"^([1-9]\d{0,6})/([1-9]\d{0,3})?(second|minute|hour|day)s?$")
SLUG = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
MAX_APPS = 32
MAX_ENTITIES = 64
SECRET_FRAGMENTS = ("password", "secret", "token", "hash", "api_key", "apikey", "private_key")
BUILTIN_FIELDS = ("created_at", "updated_at")


def api_platform_active(spec: Spec) -> bool:
    return spec.api_platform is not None and spec.api_platform.enabled


def check_api_platform(spec: Spec, entities: dict[str, SpecEntity], add: Add) -> None:
    block = spec.api_platform
    if block is None:
        return
    protected = (
        {(f.entity, f.field) for f in spec.regulated.fields}  # type: ignore[union-attr]
        if regulated_active(spec)
        else set()
    )
    if block.enabled:
        if spec.auth is None:
            add("api_platform", "api_platform_needs_auth", "the API platform needs auth (keys are managed by signed-in administrators)")
        if not block.roles:
            add("api_platform.roles", "api_platform_needs_roles", "name at least one role that may manage keys and apps (default deny)")
        if not block.entities:
            add("api_platform.entities", "api_platform_needs_entities", "list at least one entity the public API may read (default deny)")
    if spec.auth is not None:
        known_roles = {r.name for r in spec.auth.roles}
        for i, role in enumerate(block.roles):
            if role not in known_roles:
                add(f"api_platform.roles[{i}]", "unknown_role", f"no auth role named {role!r}")
    if len(block.entities) > MAX_ENTITIES or len(block.apps) > MAX_APPS:
        add("api_platform", "too_many", "too many public entities or apps")
    for field_name, value in (("rate_limit", block.rate_limit), ("sandbox_rate_limit", block.sandbox_rate_limit)):
        if LIMIT.match(value) is None:
            add(f"api_platform.{field_name}", "invalid_rate_limit", f"{value!r} is not a limit like 60/minute")

    # What per-user rules hide must not leave through a tenant-wide key: rows narrowed by owner / role / custom filter
    # rules, entities under abac / pbac policies, fields with a read-role rule. Refused, never silently widened.
    row_rules: dict[str, set[str]] = {}
    if spec.auth is not None:
        for perm in spec.auth.permissions:
            if perm.row_rule:
                row_rules.setdefault(perm.entity, set()).add(perm.row_rule)
    tenant_wide = spec.auth is not None and spec.auth.multi_tenant
    model = spec.authorization.model if spec.authorization is not None else "rbac"
    restricted = (
        {(fa.entity, fa.field) for fa in spec.authorization.field_access if fa.read_roles is not None}
        if spec.authorization is not None
        else set()
    )
    exposed: dict[str, set[str]] = {}
    for i, pe in enumerate(block.entities):
        path = f"api_platform.entities[{i}]"
        entity = entities.get(pe.entity)
        if entity is None:
            add(f"{path}.entity", "unknown_entity", f"no entity named {pe.entity!r}")
            continue
        if pe.entity in exposed:
            add(f"{path}.entity", "duplicate_entity", f"{pe.entity} is listed twice")
        exposed.setdefault(pe.entity, set())
        hidden_rules = sorted(row_rules.get(pe.entity, set()) - {"tenant"})
        if hidden_rules:
            add(f"{path}.entity", "public_entity_row_rule", f"{pe.entity} has row rules ({', '.join(hidden_rules)}) that a key cannot honour: it cannot be public")
        if model != "rbac":
            add(f"{path}.entity", "public_entity_policy", f"{pe.entity} is governed by {model} policies that a key cannot honour: it cannot be public")
        if tenant_wide and "tenant" not in row_rules.get(pe.entity, set()):
            add(f"{path}.entity", "public_entity_not_tenant_scoped", f"{pe.entity} has no tenant row rule, so every tenant's key would read all its rows")
        if not pe.fields:
            add(f"{path}.fields", "public_entity_needs_fields", f"list the fields of {pe.entity} the public API returns (default deny)")
        by_name = {f.name for f in entity.fields}
        for j, name in enumerate(pe.fields):
            exposed[pe.entity].add(name)
            if name != "id" and name not in by_name and name not in BUILTIN_FIELDS:
                add(f"{path}.fields[{j}]", "unknown_field", f"{pe.entity} has no field named {name!r}")
            elif (pe.entity, name) in restricted:
                add(f"{path}.fields[{j}]", "public_field_restricted", f"{pe.entity}.{name} has a read-role rule (field_access): it cannot be public")
            elif (pe.entity, name) in protected:
                add(f"{path}.fields[{j}]", "public_field_protected", f"{pe.entity}.{name} is protected (regulated): it never leaves through the public API")
            elif any(fragment in name.lower() for fragment in SECRET_FRAGMENTS):
                add(f"{path}.fields[{j}]", "public_field_secret", f"{pe.entity}.{name} looks like a secret: it cannot be public")
        if len(set(pe.fields)) != len(pe.fields):
            add(f"{path}.fields", "duplicate_field", "a field is listed twice")

    seen: set[str] = set()
    for i, app in enumerate(block.apps):
        path = f"api_platform.apps[{i}]"
        if not SLUG.match(app.name):
            add(f"{path}.name", "invalid_app_name", f"{app.name!r} is not a slug (lowercase letters, digits, - _)")
        elif app.name in seen:
            add(f"{path}.name", "duplicate_app", f"app {app.name!r} is listed twice")
        seen.add(app.name)
        if not app.scopes:
            add(f"{path}.scopes", "app_needs_scopes", "an app asks for at least one entity (read scope)")
        for j, scope in enumerate(app.scopes):
            if scope not in exposed:
                add(f"{path}.scopes[{j}]", "app_scope_not_public", f"{scope!r} is not a public entity of this project")
        for j, event in enumerate(app.events):
            if not SLUG.match(event):
                add(f"{path}.events[{j}]", "invalid_event_type", f"{event!r} is not a slug")
