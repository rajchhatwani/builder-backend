"""Validation for the `authorization` block (ABAC / PBAC policies).

Kept apart from validation.py, which calls `check_authorization`. Issues are reported through the
`add(path, code, message)` callable it passes in. The grammar itself lives in authz_engine (the
module that ships into generated projects); this module adds what only the builder can know: the
entities, fields and roles of the spec, and the types of everything a condition compares.
"""

import ipaddress
import re
import uuid
from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Any

from app.core import authz_engine as eng
from app.core.enums import AuthorizationModel
from app.core.spec_models import Spec, SpecAuth, SpecEntity, SpecPolicy

Add = Callable[[str, str, str], None]

_ID_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")
MAX_DESCRIPTION = 300

# Spec field types a policy may look at, as the engine's comparison kinds. `json` and `file` are
# opaque: there is nothing sensible to compare them with.
FIELD_KIND = {
    "string": "string",
    "text": "string",
    "enum": "string",
    "integer": "integer",
    "bigint": "integer",
    "float": "number",
    "decimal": "number",
    "boolean": "boolean",
    "date": "date",
    "datetime": "datetime",
    "uuid": "uuid",
}
CUSTOM_FIELD_KIND = {
    "string": "string",
    "text": "string",
    "email": "string",
    "phone": "string",
    "url": "string",
    "enum": "string",
    "integer": "integer",
    "float": "number",
    "boolean": "boolean",
    "date": "date",
    "datetime": "datetime",
}
# Present on every generated table (created_by_id is added when a policy refers to it).
BUILTIN_RESOURCE = {
    "id": "uuid",
    "created_at": "datetime",
    "updated_at": "datetime",
    "created_by_id": "uuid",
}
ORDERED_KINDS = {"integer", "number", "date", "datetime", "string"}
NUMERIC = {"integer", "number"}


def authz_active(spec: Spec) -> bool:
    return spec.authorization is not None and spec.authorization.model in (
        AuthorizationModel.abac,
        AuthorizationModel.pbac,
    )


def subject_attributes(auth: SpecAuth | None) -> dict[str, str]:
    """Attribute name -> kind of the signed-in person, as the generated code can supply them."""
    attrs = {"id": "uuid", "email": "string", "roles": "list"}
    if auth is None:
        return attrs
    if auth.multi_tenant:
        attrs["tenant_id"] = "uuid"
    if auth.provider == "builtin":
        for custom in auth.registration.custom_fields:
            kind = CUSTOM_FIELD_KIND.get(custom.type)
            if kind is not None:
                attrs[custom.name] = kind
    return attrs


def entity_attributes(entity: SpecEntity) -> dict[str, str]:
    attrs = dict(BUILTIN_RESOURCE)
    for f in entity.fields:
        kind = FIELD_KIND.get(f.type)
        if kind is not None:
            attrs[f.name] = kind
    return attrs


def entity_operations(entity: SpecEntity) -> set[str]:
    return set(entity.options.operations)


def policy_entities(policy: SpecPolicy, entities: dict[str, SpecEntity]) -> list[str]:
    """Names of the entities the policy's actions reach (unknown names are reported elsewhere)."""
    if any(a == "*" for a in policy.actions):
        return sorted(entities)
    return sorted({a.split(".", 1)[0] for a in policy.actions if a.split(".", 1)[0] in entities})


def references_created_by(policy: SpecPolicy) -> bool:
    if policy.when is None:
        return False
    try:
        node = eng.normalize_node(policy.when)
    except eng.PolicyError:
        return False
    return any(
        side in leaf and leaf[side].get("resource") == "created_by_id"
        for leaf in eng.walk_leaves(node)
        for side in ("left", "right")
    )


def policies_for_entity(spec: Spec, entity_name: str) -> list[SpecPolicy]:
    if not authz_active(spec):
        return []
    entities = {e.name: e for e in spec.entities}
    assert spec.authorization is not None
    return [p for p in spec.authorization.policies if entity_name in policy_entities(p, entities)]


# -- the check --------------------------------------------------------------------------------


def check_authorization(spec: Spec, entities: dict[str, SpecEntity], add: Add) -> None:
    block = spec.authorization
    if block is None:
        return
    valid_models = {m.value for m in AuthorizationModel}
    if block.model not in valid_models:
        add("authorization.model", "invalid_value", f"must be one of {sorted(valid_models)}")
        return
    if block.model == AuthorizationModel.rbac:
        if block.policies or block.attachments:
            add(
                "authorization",
                "authz.unused_policies",
                "policies are only used with the abac or pbac model; switch the model or remove them",
            )
        return

    auth = spec.auth
    if auth is None or not auth.enabled:
        add(
            "authorization.model",
            "authz.needs_auth",
            f"{block.model} decides what signed-in people may do, so sign-in must be switched on",
        )
        return
    if auth.permissions:
        add(
            "auth.permissions",
            "authz.mixed_models",
            f"the project uses {block.model}: remove the role permissions "
            "(or switch the authorization model back to rbac), so there is one source of truth",
        )
    if len(block.policies) > eng.MAX_POLICIES:
        add("authorization.policies", "too_many", f"at most {eng.MAX_POLICIES} policies")
    if not block.policies:
        add(
            "authorization.policies",
            "authz.no_policies",
            f"{block.model} denies everything by default: add at least one allow policy",
        )

    roles = {r.name for r in auth.roles} if auth.provider == "builtin" else _keycloak_roles(auth)
    subject = subject_attributes(auth)
    seen: set[str] = set()
    for i, policy in enumerate(block.policies):
        _check_policy(block.model, policy, i, entities, subject, seen, add)

    _check_attachments(block.model, block.attachments, block.policies, roles, add)


def _keycloak_roles(auth: SpecAuth) -> set[str]:
    return {r.name for r in auth.roles}


def _check_policy(
    model: str,
    policy: SpecPolicy,
    index: int,
    entities: dict[str, SpecEntity],
    subject: dict[str, str],
    seen: set[str],
    add: Add,
) -> None:
    path = f"authorization.policies[{index}]"
    if not _ID_RE.fullmatch(policy.id):
        add(
            f"{path}.id",
            "invalid_value",
            "use lowercase letters, digits and underscores, starting with a letter (max 40)",
        )
    elif policy.id in seen:
        add(f"{path}.id", "duplicate", f"policy id {policy.id!r} is used twice")
    seen.add(policy.id)
    if len(policy.description) > MAX_DESCRIPTION:
        add(f"{path}.description", "too_long", f"at most {MAX_DESCRIPTION} characters")
    if policy.effect not in ("allow", "deny"):
        add(f"{path}.effect", "invalid_value", "must be 'allow' or 'deny'")
    if not policy.actions:
        add(f"{path}.actions", "authz.no_actions", "name at least one action, e.g. 'Order.list'")

    reach: set[str] = set()
    ops_in_play: set[str] = set()
    for j, action in enumerate(policy.actions):
        found = _check_action(action, entities, f"{path}.actions[{j}]", add)
        if found is not None:
            reach.update(found[0])
            ops_in_play.update(found[1])

    if policy.when is None:
        _check_unconditional(model, policy, ops_in_play, path, add)
        return
    try:
        node = eng.normalize_node(policy.when)
    except eng.PolicyError as exc:
        add(f"{path}.when", "authz.bad_condition", str(exc))
        return
    depth, nodes = eng.node_stats(node)
    if depth > eng.MAX_DEPTH or nodes > eng.MAX_NODES:
        add(
            f"{path}.when",
            "authz.condition_too_large",
            f"at most {eng.MAX_DEPTH} levels and {eng.MAX_NODES} conditions",
        )
        return
    resource = _common_resource_attributes(sorted(reach), entities, path, add)
    for k, leaf in enumerate(eng.walk_leaves(node)):
        _check_leaf(leaf, subject, resource, entities, sorted(reach), f"{path}.when", k, add)


def _check_action(
    action: str, entities: dict[str, SpecEntity], path: str, add: Add
) -> tuple[set[str], set[str]] | None:
    if action == "*":
        return set(entities), set(eng.OPERATIONS)
    entity, dot, op = action.partition(".")
    if not dot or entity not in entities:
        add(path, "authz.unknown_action", f"{action!r}: use 'Entity.operation', 'Entity.*' or '*'")
        return None
    allowed = entity_operations(entities[entity])
    if op == "*":
        return {entity}, allowed
    if op not in eng.OPERATIONS or op not in allowed:
        add(
            path,
            "authz.unknown_action",
            f"{entity} has no {op!r} operation (it offers: {', '.join(sorted(allowed)) or 'none'})",
        )
        return None
    return {entity}, {op}


def _check_unconditional(
    model: str, policy: SpecPolicy, ops: set[str], path: str, add: Add
) -> None:
    writes = ops & {"create", "replace", "update", "delete"}
    if policy.effect == "allow" and writes and model == AuthorizationModel.abac:
        add(
            f"{path}.when",
            "authz.open_write",
            f"policy {policy.id!r} lets every signed-in person {', '.join(sorted(writes))} "
            "without any condition; add a condition (for example created_by_id equals your id)",
        )
    if (
        policy.effect == "deny"
        and any(a == "*" for a in policy.actions)
        and model == AuthorizationModel.abac
    ):
        add(f"{path}.when", "authz.deny_all", f"policy {policy.id!r} denies everything to everyone")


def _check_attachments(
    model: str,
    attachments: dict[str, list[str]],
    policies: list[SpecPolicy],
    roles: set[str],
    add: Add,
) -> None:
    ids = {p.id for p in policies}
    if model == AuthorizationModel.abac:
        if attachments:
            add(
                "authorization.attachments",
                "authz.attachments_not_used",
                "under abac every policy applies to everyone; attach policies to roles with pbac",
            )
        return
    attached: set[str] = set()
    for principal, policy_ids in attachments.items():
        path = f"authorization.attachments[{principal}]"
        if principal == "public":
            add(
                path,
                "authz.public_not_supported",
                "public (signed-out) access is not available with pbac yet; use rbac for public routes",
            )
        elif principal != "*" and principal not in roles:
            add(path, "authz.unknown_role", f"{principal!r} is not a role of this project (or '*')")
        for pid in policy_ids:
            if pid not in ids:
                add(path, "authz.unknown_policy", f"policy {pid!r} does not exist")
            attached.add(pid)
    for policy in policies:
        if policy.id not in attached:
            add(
                "authorization.attachments",
                "authz.unattached_policy",
                f"policy {policy.id!r} is not attached to any role or to '*', so it never applies",
            )


# -- conditions: attributes and types -----------------------------------------------------------


def _common_resource_attributes(
    reach: list[str], entities: dict[str, SpecEntity], path: str, add: Add
) -> dict[str, str]:
    """Attributes every entity the policy reaches has, with one agreed kind. Others are errors
    only if a condition uses them (reported in _check_leaf)."""
    if not reach:
        return {}
    common = entity_attributes(entities[reach[0]])
    for name in reach[1:]:
        other = entity_attributes(entities[name])
        common = {k: v for k, v in common.items() if other.get(k) == v}
    return common


def _operand(
    operand: dict[str, Any],
    subject: dict[str, str],
    resource: dict[str, str],
    reach: list[str],
    entities: dict[str, SpecEntity],
    path: str,
    add: Add,
) -> tuple[str, str | None, Any]:
    """(category, kind, extra). kind None means the problem was reported and checking stops."""
    ((category, name),) = operand.items()
    if category == "subject":
        kind = subject.get(name)
        if kind is None:
            add(
                path,
                "authz.unknown_subject_attribute",
                f"people have no attribute {name!r} (available: {', '.join(sorted(subject))})",
            )
        return category, kind, name
    if category == "env":
        kind = eng.ENV_ATTRIBUTES.get(name)
        if kind is None:
            add(
                path,
                "authz.unknown_env_attribute",
                f"unknown environment attribute {name!r} (available: {', '.join(sorted(eng.ENV_ATTRIBUTES))})",
            )
        return category, kind, name
    if category == "resource":
        kind = resource.get(name)
        if kind is None:
            where = ", ".join(reach) or "its entities"
            add(
                path,
                "authz.unknown_resource_attribute",
                f"{name!r} is not an attribute (with the same type) of {where}",
            )
        return category, kind, name
    return category, _literal_kind(name, path, add), name


def _literal_kind(value: Any, path: str, add: Add) -> str | None:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        kinds = {_literal_kind(v, path, add) for v in value}
        if None in kinds or not value:
            add(
                path,
                "authz.bad_literal",
                "a list needs at least one value, all strings, numbers or booleans",
            )
            return None
        if len(value) > eng.MAX_LIST_LITERAL:
            add(path, "authz.bad_literal", f"a list may hold at most {eng.MAX_LIST_LITERAL} values")
            return None
        if len(kinds) > 1 and not kinds <= NUMERIC:
            add(path, "authz.bad_literal", "all values in a list must have the same type")
            return None
        return "list:" + (
            "number" if kinds <= NUMERIC and len(kinds) > 1 else next(iter(kinds)) or ""
        )
    add(
        path,
        "authz.bad_literal",
        "a literal is a string, number, boolean or list (use is_null to test for missing)",
    )
    return None


def _compatible(kind_a: str, kind_b: str) -> bool:
    return kind_a == kind_b or (kind_a in NUMERIC and kind_b in NUMERIC)


def _literal_fits(value: Any, kind: str) -> bool:
    """A string literal compared with a uuid / date / datetime attribute must parse as one."""
    if not isinstance(value, str):
        return False
    try:
        if kind == "uuid":
            uuid.UUID(value)
        elif kind == "date":
            date.fromisoformat(value)
        elif kind == "datetime":
            datetime.fromisoformat(value)
        else:
            return False
    except ValueError:
        return False
    return True


def _check_leaf(
    leaf: Mapping[str, Any],
    subject: dict[str, str],
    resource: dict[str, str],
    entities: dict[str, SpecEntity],
    reach: list[str],
    base: str,
    index: int,
    add: Add,
) -> None:
    path = f"{base}[{index}]"
    op = leaf["op"]
    lcat, lkind, lname = _operand(leaf["left"], subject, resource, reach, entities, path, add)
    if lkind is None:
        return
    if op in eng.UNARY_OPS:
        if lkind.startswith("list"):
            add(path, "authz.bad_operand", f"{op} cannot be used on a list")
        return
    rcat, rkind, rname = _operand(leaf["right"], subject, resource, reach, entities, path, add)
    if rkind is None:
        return

    if op == "ip_in":
        _check_ip_in(lcat, lkind, rcat, rkind, rname, leaf, path, add)
        return
    if "resource" in (lcat, rcat) and rcat == "resource" and op in eng.LIST_OPS:
        add(
            path,
            "authz.in_needs_list",
            "the right side of in / not_in must be a list, not a resource attribute",
        )
        return
    if op in eng.LIST_OPS:
        _check_membership(op, lcat, lkind, lname, rcat, rkind, rname, path, add)
        return
    # eq, ne, lt, lte, gt, gte
    if lkind.startswith("list") or rkind.startswith("list") or lkind == "list" or rkind == "list":
        add(
            path,
            "authz.bad_operand",
            f"{op} compares single values; use in / not_in (or contains) with a list",
        )
        return
    if op in ("lt", "lte", "gt", "gte") and (
        lkind not in ORDERED_KINDS or rkind not in ORDERED_KINDS
    ):
        add(
            path,
            "authz.bad_operand",
            f"{op} needs numbers, dates or text, not {lkind if lkind not in ORDERED_KINDS else rkind}",
        )
        return
    if _compatible(lkind, rkind):
        _check_enum_literal(lcat, lname, rcat, rname, entities, reach, path, add)
        return
    for cat, kind, name, other_kind in ((rcat, rkind, rname, lkind), (lcat, lkind, lname, rkind)):
        if cat == "literal" and kind == "string" and _literal_fits(name, other_kind):
            return
    add(path, "authz.type_mismatch", f"cannot compare {lkind} with {rkind}")


def _check_membership(
    op: str,
    lcat: str,
    lkind: str,
    lname: Any,
    rcat: str,
    rkind: str,
    rname: Any,
    path: str,
    add: Add,
) -> None:
    if lkind.startswith("list") or lkind == "list":
        add(
            path,
            "authz.bad_operand",
            f"the left side of {op} must be a single value (swap the sides, or use contains)",
        )
        return
    if rkind == "list":  # subject.roles
        if lkind != "string":
            add(path, "authz.type_mismatch", f"roles are text; cannot test {lkind} against them")
        return
    if not rkind.startswith("list:"):
        add(path, "authz.bad_operand", f"the right side of {op} must be a list")
        return
    element = rkind.split(":", 1)[1]
    if _compatible(lkind, element):
        return
    if (
        lkind in ("uuid", "date", "datetime")
        and element == "string"
        and all(_literal_fits(v, lkind) for v in rname)
    ):
        return
    add(path, "authz.type_mismatch", f"cannot test {lkind} against a list of {element}")


def _check_enum_literal(
    lcat: str,
    lname: Any,
    rcat: str,
    rname: Any,
    entities: dict[str, SpecEntity],
    reach: list[str],
    path: str,
    add: Add,
) -> None:
    """A literal compared with an enum field must be one of its values (a typo never matches)."""
    for res_cat, res_name, lit_cat, lit_value in (
        (lcat, lname, rcat, rname),
        (rcat, rname, lcat, lname),
    ):
        if res_cat == "resource" and lit_cat == "literal" and isinstance(lit_value, str):
            for entity in reach:
                spec_field = next((f for f in entities[entity].fields if f.name == res_name), None)
                if (
                    spec_field is not None
                    and spec_field.type == "enum"
                    and spec_field.enum_values
                    and lit_value not in spec_field.enum_values
                ):
                    add(
                        path,
                        "authz.bad_enum_value",
                        f"{lit_value!r} is not a value of {entity}.{res_name} ({', '.join(spec_field.enum_values)})",
                    )


def _check_ip_in(
    lcat: str,
    lkind: str,
    rcat: str,
    rkind: str,
    rname: Any,
    leaf: Mapping[str, Any],
    path: str,
    add: Add,
) -> None:
    if lcat == "resource" or rcat == "resource":
        add(
            path,
            "authz.bad_operand",
            "ip_in compares the caller's address; it cannot use a resource attribute",
        )
        return
    if lkind != "string":
        add(path, "authz.type_mismatch", "ip_in needs an address (env.client_ip)")
    if rcat != "literal" or not rkind.startswith("list:"):
        add(path, "authz.bad_operand", "ip_in needs a list of networks such as ['10.0.0.0/8']")
        return
    for network in rname:
        try:
            ipaddress.ip_network(network, strict=False)
        except (ValueError, TypeError):
            add(path, "authz.bad_network", f"{network!r} is not a network like 10.0.0.0/8")
