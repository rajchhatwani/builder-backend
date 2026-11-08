"""Policy engine for ABAC and PBAC. One module, two homes.

This file is the single source of truth. The builder imports it (simulator, validation, tests)
and the generator copies it **byte for byte** into every project that uses attribute- or
policy-based access (`app/auth/policy.py`). What the simulator shows is therefore what ships.

Rules the whole design rests on (each has tests):
  * default deny: no applicable allow policy means no access;
  * deny overrides: one matching deny policy beats any number of allow policies;
  * no code execution: conditions are plain data (`all` / `any` groups of `left op right`), there is
    no expression language, no `eval`, no attribute lookup by name on objects;
  * every attribute is checked against an allow-list when the policy data is loaded; a value that
    is missing or None makes a comparison False (never an error, never "unknown");
  * the same condition gives the same answer in Python (a row, a payload, the simulator) and in SQL
    (list, get, update and delete are filtered in the database, so pagination and counts can never
    leak rows). Every SQL leaf can only be true or false, never NULL: that, plus the
    absence of `not`, is what makes the two agree.

Policy data shapes (JSON-compatible):
    policy      {"effect": "allow"|"deny", "actions": ["Order.list", "Order.*", "*"],
                 "when": node|None}
    node        {"all": [node, ...]} | {"any": [node, ...]} | leaf
    leaf        {"left": operand, "op": op, "right": operand}      (`right` omitted for unary ops)
    operand     {"subject": "id"} | {"resource": "status"} | {"env": "hour_utc"} | {"literal": 5}
"""

from __future__ import annotations

import ipaddress
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

MAX_DEPTH = 4
MAX_NODES = 24
MAX_LIST_LITERAL = 100
MAX_POLICIES = 200

OPERATIONS = ("list", "get", "create", "replace", "update", "delete", "head")
ENV_ATTRIBUTES = {"hour_utc": "integer", "weekday_utc": "integer", "client_ip": "string"}

COMPARE_OPS = ("eq", "ne", "lt", "lte", "gt", "gte")
LIST_OPS = ("in", "not_in")
UNARY_OPS = ("is_null", "not_null")
ALL_OPS = (*COMPARE_OPS, *LIST_OPS, *UNARY_OPS, "contains", "ip_in")

OPERAND_KINDS = ("subject", "resource", "env", "literal")


class PolicyError(Exception):
    """The policy data itself is malformed. Loading it fails; nothing is ever half-applied."""


class ResourceRequired(Exception):
    """An operand names a resource attribute but no row was supplied."""


# -- normalisation and comparison ------------------------------------------------------------


def _norm(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return value
    if isinstance(value, datetime):
        return value
    return value


def _parse_scalar(value: Any, ftype: str | None) -> Any:
    """A policy literal as the Python value of a column of type `ftype` (best effort, strict)."""
    if value is None or ftype is None:
        return value
    try:
        if ftype == "uuid":
            return uuid.UUID(str(value))
        if ftype == "datetime":
            return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        if ftype == "date":
            return value if isinstance(value, date) else date.fromisoformat(str(value))
        if ftype == "integer":
            return int(value) if not isinstance(value, bool) else value
        if ftype == "number":
            return value if isinstance(value, int | float | Decimal) else Decimal(str(value))
    except (ValueError, TypeError, ArithmeticError):
        return value
    return value


def _as_comparable(value: Any) -> Any:
    """Make a UUID, a UUID string, a datetime and its ISO string comparable with each other."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=None)
    return value


def compare(op: str, a: Any, b: Any = None) -> bool:
    """Two-valued comparison: None (or a type mismatch) makes it False, except is_null/not_null."""
    if op == "is_null":
        return a is None
    if op == "not_null":
        return a is not None
    if op == "ip_in":
        return _ip_in(a, b)
    if a is None or b is None:
        return False
    if op in LIST_OPS:
        if isinstance(b, str | bytes) or not isinstance(b, Sequence | set | frozenset):
            return False
        wanted = _as_comparable(a)
        member = any(_as_comparable(x) == wanted for x in b if x is not None)
        return member if op == "in" else not member
    a, b = _as_comparable(a), _as_comparable(b)
    try:
        match op:
            case "eq":
                return bool(a == b)
            case "ne":
                return bool(a != b)
            case "lt":
                return bool(a < b)
            case "lte":
                return bool(a <= b)
            case "gt":
                return bool(a > b)
            case "gte":
                return bool(a >= b)
    except TypeError:
        return False
    raise PolicyError(f"unknown operator {op!r}")


def _ip_in(address: Any, networks: Any) -> bool:
    if not isinstance(address, str) or isinstance(networks, str) or networks is None:
        return False
    try:
        ip = ipaddress.ip_address(address)
        return any(ip in ipaddress.ip_network(n, strict=False) for n in networks)
    except ValueError:
        return False


# -- normal form and validation of the policy data -----------------------------------------------


def _operand_key(operand: Any) -> tuple[str, Any]:
    if not isinstance(operand, Mapping) or len(operand) != 1:
        raise PolicyError("an operand has exactly one of: subject, resource, env, literal")
    ((kind, value),) = operand.items()
    if kind not in OPERAND_KINDS:
        raise PolicyError(f"unknown operand kind {kind!r}")
    return kind, value


def normalize_node(node: Any) -> dict[str, Any]:
    """Canonical form of a condition: `contains(L, R)` becomes `in(R, L)`. Raises PolicyError."""
    if not isinstance(node, Mapping):
        raise PolicyError("a condition must be an object")
    if "all" in node or "any" in node:
        key = "all" if "all" in node else "any"
        if len(node) != 1 or not isinstance(node[key], list) or not node[key]:
            raise PolicyError(f"'{key}' needs a non-empty list and nothing else")
        return {key: [normalize_node(child) for child in node[key]]}
    unknown = set(node) - {"left", "op", "right"}
    if unknown or "left" not in node or "op" not in node:
        raise PolicyError("a comparison has 'left', 'op' and (except is_null/not_null) 'right'")
    op = node["op"]
    if op not in ALL_OPS:
        raise PolicyError(f"unknown operator {op!r}")
    _operand_key(node["left"])
    if op in UNARY_OPS:
        if "right" in node:
            raise PolicyError(f"{op} takes no right-hand side")
        return {"left": dict(node["left"]), "op": op}
    if "right" not in node:
        raise PolicyError(f"{op} needs a right-hand side")
    _operand_key(node["right"])
    if op == "contains":
        return {"left": dict(node["right"]), "op": "in", "right": dict(node["left"])}
    return {"left": dict(node["left"]), "op": op, "right": dict(node["right"])}


def node_stats(node: Mapping[str, Any]) -> tuple[int, int]:
    """(depth, number of nodes) of a normalised condition."""
    for key in ("all", "any"):
        if key in node:
            parts = [node_stats(child) for child in node[key]]
            return 1 + max(d for d, _ in parts), 1 + sum(n for _, n in parts)
    return 1, 1


def walk_leaves(node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for key in ("all", "any"):
        if key in node:
            return [leaf for child in node[key] for leaf in walk_leaves(child)]
    return [node]


def uses_resource(node: Mapping[str, Any]) -> bool:
    return any(
        "resource" in leaf.get(side, {}) for leaf in walk_leaves(node) for side in ("left", "right")
    )


# -- the policy set --------------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicySet:
    """Everything needed to decide, in plain data. Built once at startup (fail closed)."""

    model: str  # "abac" | "pbac"
    policies: Mapping[str, Mapping[str, Any]]  # id -> {effect, actions, when}
    attachments: Mapping[str, tuple[str, ...]]  # role name or "*" -> policy ids
    field_types: Mapping[str, Mapping[str, str]] = field(
        default_factory=dict
    )  # entity -> field -> type
    subject_attributes: frozenset[str] = frozenset({"id", "roles", "email", "tenant_id"})


def load_policy_set(raw: Mapping[str, Any]) -> PolicySet:
    """Validate and freeze policy data. Raises PolicyError on anything unexpected."""
    model = raw.get("model")
    if model not in ("abac", "pbac"):
        raise PolicyError(f"unknown authorization model {model!r}")
    policies: dict[str, dict[str, Any]] = {}
    raw_policies = raw.get("policies", {})
    if not isinstance(raw_policies, Mapping) or len(raw_policies) > MAX_POLICIES:
        raise PolicyError(f"policies must be an object with at most {MAX_POLICIES} entries")
    for pid, policy in raw_policies.items():
        if policy.get("effect") not in ("allow", "deny"):
            raise PolicyError(f"policy {pid}: effect must be allow or deny")
        actions = policy.get("actions")
        if (
            not isinstance(actions, list)
            or not actions
            or not all(isinstance(a, str) for a in actions)
        ):
            raise PolicyError(f"policy {pid}: actions must be a non-empty list of strings")
        when = policy.get("when")
        normalised = normalize_node(when) if when is not None else None
        if normalised is not None:
            depth, nodes = node_stats(normalised)
            if depth > MAX_DEPTH or nodes > MAX_NODES:
                raise PolicyError(f"policy {pid}: condition is too deep or too large")
        if normalised is not None:
            _check_attributes(pid, normalised, actions, raw)
        policies[pid] = {"effect": policy["effect"], "actions": tuple(actions), "when": normalised}
    attachments: dict[str, tuple[str, ...]] = {}
    for principal, ids in raw.get("attachments", {}).items():
        unknown = [i for i in ids if i not in policies]
        if unknown:
            raise PolicyError(f"attachment {principal!r} names unknown policies {unknown}")
        attachments[principal] = tuple(ids)
    if model == "abac" and set(attachments) - {"*"}:
        raise PolicyError("under abac every policy applies to everyone; use pbac to attach by role")
    return PolicySet(
        model=model,
        policies=policies,
        attachments=attachments,
        field_types={e: dict(f) for e, f in raw.get("field_types", {}).items()},
        subject_attributes=frozenset(
            raw.get("subject_attributes", ("id", "roles", "email", "tenant_id"))
        ),
    )


def _check_attributes(
    pid: str, node: Mapping[str, Any], actions: list[str], raw: Mapping[str, Any]
) -> None:
    """Every attribute a policy names must exist: subject attributes in the allow-list, env
    from the fixed list, resource attributes in every entity the policy's actions can reach."""
    subject_ok = set(raw.get("subject_attributes", ("id", "roles", "email", "tenant_id")))
    field_types: Mapping[str, Mapping[str, str]] = raw.get("field_types", {})
    entities = (
        set(field_types)
        if any(a == "*" for a in actions)
        else {a.split(".", 1)[0] for a in actions}
    )
    for leaf in walk_leaves(node):
        for side in ("left", "right"):
            if side not in leaf:
                continue
            kind, name = _operand_key(leaf[side])
            if kind == "subject" and name not in subject_ok:
                raise PolicyError(f"policy {pid}: unknown subject attribute {name!r}")
            if kind == "env" and name not in ENV_ATTRIBUTES:
                raise PolicyError(f"policy {pid}: unknown environment attribute {name!r}")
            if kind == "resource":
                for entity in entities:
                    if name not in field_types.get(entity, {}):
                        raise PolicyError(f"policy {pid}: {entity} has no attribute {name!r}")
            if kind == "literal" and isinstance(name, list) and len(name) > MAX_LIST_LITERAL:
                raise PolicyError(f"policy {pid}: a list has more than {MAX_LIST_LITERAL} values")


def _action_matches(pattern: str, entity: str, op: str) -> bool:
    return pattern == "*" or pattern == f"{entity}.{op}" or pattern == f"{entity}.*"


def applicable(
    pset: PolicySet, roles: Sequence[str], entity: str, op: str
) -> list[tuple[str, Mapping[str, Any]]]:
    """Policies that apply to someone holding `roles` for this action, in a stable order."""
    ids: list[str] = list(pset.attachments.get("*", ()))
    for role in sorted(set(roles)):
        ids.extend(pset.attachments.get(role, ()))
    seen: set[str] = set()
    result: list[tuple[str, Mapping[str, Any]]] = []
    for pid in ids:
        if pid in seen:
            continue
        seen.add(pid)
        policy = pset.policies[pid]
        if any(_action_matches(a, entity, op) for a in policy["actions"]):
            result.append((pid, policy))
    return result


# -- evaluation against a concrete row (Python) -------------------------------------------------


@dataclass(frozen=True)
class Context:
    subject: Mapping[str, Any]  # id, roles (effective), email, tenant_id, custom attributes
    env: Mapping[str, Any] = field(default_factory=dict)  # hour_utc, weekday_utc, client_ip


def _value(operand: Mapping[str, Any], ctx: Context, resource: Mapping[str, Any] | None) -> Any:
    kind, name = _operand_key(operand)
    if kind == "literal":
        return name
    if kind == "subject":
        return ctx.subject.get(name)
    if kind == "env":
        return ctx.env.get(name)
    if resource is None:
        raise ResourceRequired(name)
    return resource.get(name)


def eval_node(
    node: Mapping[str, Any],
    ctx: Context,
    resource: Mapping[str, Any] | None,
    types: Mapping[str, str] | None = None,
) -> bool:
    if "all" in node:
        return all(eval_node(child, ctx, resource, types) for child in node["all"])
    if "any" in node:
        return any(eval_node(child, ctx, resource, types) for child in node["any"])
    op = node["op"]
    left_operand = node["left"]
    if op in UNARY_OPS:
        return compare(op, _value(left_operand, ctx, resource))
    right_operand = node["right"]
    left = _typed(left_operand, _value(left_operand, ctx, resource), types, other=right_operand)
    right = _typed(right_operand, _value(right_operand, ctx, resource), types, other=left_operand)
    return compare(op, left, right)


def _typed(
    operand: Mapping[str, Any], value: Any, types: Mapping[str, str] | None, other: Any = None
) -> Any:
    """Literals are parsed as the type of the resource attribute they are compared with."""
    if types is None or "literal" not in operand:
        return value
    kind, name = _operand_key(other) if other else ("", None)
    ftype = types.get(str(name)) if kind == "resource" else None
    if isinstance(value, list):
        return [_parse_scalar(v, ftype) for v in value]
    return _parse_scalar(value, ftype)


# -- decisions ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    allow_matched: tuple[str, ...] = ()
    deny_matched: tuple[str, ...] = ()


def decide(
    pset: PolicySet,
    ctx: Context,
    entity: str,
    op: str,
    resource: Mapping[str, Any] | None,
) -> Decision:
    """Allow or deny one concrete request against one concrete row. Used by the simulator and by
    write checks. `resource` is the row (or the incoming payload for create)."""
    types = pset.field_types.get(entity, {})
    roles = list(ctx.subject.get("roles") or ())
    pols = applicable(pset, roles, entity, op)
    allows: list[str] = []
    denies: list[str] = []
    for pid, policy in pols:
        when = policy["when"]
        hit = (
            True
            if when is None
            else eval_node(when, ctx, resource if resource is not None else {}, types)
        )
        if hit:
            (allows if policy["effect"] == "allow" else denies).append(pid)
    if denies:
        return Decision(
            False, "denied by policy " + ", ".join(denies), tuple(allows), tuple(denies)
        )
    if allows:
        return Decision(True, "allowed by policy " + ", ".join(allows), tuple(allows))
    if not any(p["effect"] == "allow" for _, p in pols):
        return Decision(False, f"no policy allows {entity}.{op} for this person (default deny)")
    return Decision(False, "no allow policy's conditions were met (default deny)")


# -- the plan the generated routes use (SQL for reads, Python for writes) -------------------------


@dataclass
class Plan:
    """What one request is allowed to do.

    allowed       False means refuse with 403 straight away (no row could ever qualify)
    row_filter    SQL clause to AND onto every query (None = no restriction beyond the above)
    check_row     Python re-check of the same decision for a row or payload (writes)
    """

    allowed: bool
    reason: str
    row_filter: Any | None = None
    check_row: Callable[[Mapping[str, Any]], bool] = field(default=lambda row: False)
    allow_ids: tuple[str, ...] = ()
    deny_ids: tuple[str, ...] = ()


def _sql_value(value: Any, ftype: str | None) -> Any:
    return _parse_scalar(value, ftype)


def _leaf_sql(
    leaf: Mapping[str, Any], ctx: Context, column: Callable[[str], Any], types: Mapping[str, str]
) -> Any:
    """A leaf that touches a resource attribute, as a SQL clause that can only be true or false."""
    import sqlalchemy as sa

    op = leaf["op"]
    left = leaf["left"]
    lkind, lname = _operand_key(left)
    if op in UNARY_OPS:
        col = column(lname)
        return col.is_(None) if op == "is_null" else col.is_not(None)
    right: Mapping[str, Any] = leaf["right"]
    rkind, rname = _operand_key(right)
    if op in LIST_OPS:
        if lkind != "resource" or rkind == "resource":
            raise PolicyError(
                "in / not_in need a resource attribute on the left and a list on the right"
            )
        col = column(lname)
        raw = right.get("literal") if rkind == "literal" else _value(right, ctx, None)
        values = [_sql_value(v, types.get(lname)) for v in (raw or ()) if v is not None]
        if not values:
            return False if op == "in" else col.is_not(None)
        clause = col.in_(values) if op == "in" else col.not_in(values)
        return sa.and_(col.is_not(None), clause)

    def side(
        operand: Mapping[str, Any], kind: str, name: Any, peer_col: str | None
    ) -> tuple[Any, bool]:
        if kind == "resource":
            return column(name), True
        value = operand.get("literal") if kind == "literal" else _value(operand, ctx, None)
        return _sql_value(value, types.get(peer_col) if peer_col else None), False

    lval, l_is_col = side(left, lkind, lname, rname if rkind == "resource" else None)
    rval, r_is_col = side(right, rkind, rname, lname if lkind == "resource" else None)
    guards = [v.is_not(None) for v, is_col in ((lval, l_is_col), (rval, r_is_col)) if is_col]
    for v, is_col in ((lval, l_is_col), (rval, r_is_col)):
        if not is_col and v is None:
            return False  # comparing with a missing value is never true
    comparison = {
        "eq": lambda a, b: a == b,
        "ne": lambda a, b: a != b,
        "lt": lambda a, b: a < b,
        "lte": lambda a, b: a <= b,
        "gt": lambda a, b: a > b,
        "gte": lambda a, b: a >= b,
    }[op](lval, rval)
    return sa.and_(*guards, comparison)


def _reduce(
    node: Mapping[str, Any], ctx: Context, column: Callable[[str], Any], types: Mapping[str, str]
) -> Any:
    """Fold everything that does not depend on the row into True/False; leave SQL for the rest."""
    import sqlalchemy as sa

    for key, combine in (("all", sa.and_), ("any", sa.or_)):
        if key in node:
            parts = [_reduce(child, ctx, column, types) for child in node[key]]
            identity, absorbing = (True, False) if key == "all" else (False, True)
            if any(p is absorbing for p in parts):
                return absorbing
            rest = [p for p in parts if p is not identity]
            if not rest:
                return identity
            return rest[0] if len(rest) == 1 else combine(*rest)
    if not uses_resource(node):
        return eval_node(node, ctx, None)
    return _leaf_sql(node, ctx, column, types)


def plan(
    pset: PolicySet,
    ctx: Context,
    entity: str,
    op: str,
    column: Callable[[str], Any],
) -> Plan:
    """What `ctx.subject` may do with `entity.op`: a SQL row filter plus a Python check."""
    import sqlalchemy as sa

    types = pset.field_types.get(entity, {})
    roles = list(ctx.subject.get("roles") or ())
    pols = applicable(pset, roles, entity, op)
    allow_pols = [(i, p) for i, p in pols if p["effect"] == "allow"]
    deny_pols = [(i, p) for i, p in pols if p["effect"] == "deny"]

    def check_row(row: Mapping[str, Any]) -> bool:
        return decide(pset, ctx, entity, op, row).allowed

    if not allow_pols:
        return Plan(
            False, f"no policy allows {entity}.{op} for this person", check_row=lambda r: False
        )

    deny_terms: list[Any] = []
    for pid, policy in deny_pols:
        reduced = True if policy["when"] is None else _reduce(policy["when"], ctx, column, types)
        if reduced is True:
            return Plan(
                False, f"denied by policy {pid}", check_row=lambda r: False, deny_ids=(pid,)
            )
        if reduced is not False:
            deny_terms.append(reduced)

    allow_terms: list[Any] = []
    unrestricted = False
    for _pid, policy in allow_pols:
        reduced = True if policy["when"] is None else _reduce(policy["when"], ctx, column, types)
        if reduced is True:
            unrestricted = True
        elif reduced is not False:
            allow_terms.append(reduced)
    if not unrestricted and not allow_terms:
        return Plan(False, "no allow policy can match", check_row=lambda r: False)

    clauses: list[Any] = []
    if not unrestricted:
        clauses.append(allow_terms[0] if len(allow_terms) == 1 else sa.or_(*allow_terms))
    if deny_terms:
        denied = deny_terms[0] if len(deny_terms) == 1 else sa.or_(*deny_terms)
        clauses.append(sa.not_(denied))  # safe: every leaf is two-valued, never NULL
    row_filter = None if not clauses else (clauses[0] if len(clauses) == 1 else sa.and_(*clauses))
    return Plan(
        True,
        "allowed",
        row_filter=row_filter,
        check_row=check_row,
        allow_ids=tuple(i for i, _ in allow_pols),
        deny_ids=tuple(i for i, _ in deny_pols),
    )
