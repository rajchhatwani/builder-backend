"""The ABAC / PBAC engine: semantics, hostile policy data, and SQL == Python == reference.

The equivalence test is the important one. It builds random policy sets and random rows, then asks
three independent implementations which rows a person may see: the engine's SQL filter (what list /
get / delete use), the engine's Python check (what create / update use) and a tiny reference
interpreter written separately below. Any disagreement would be an access-control bug.
"""

import json
import random
import uuid
from typing import Any

import pytest
import sqlalchemy as sa

from app.core import authz_engine as eng
from app.core.authz_engine import Context, PolicyError, decide, load_policy_set, plan

DOC_FIELDS = {
    "id": "uuid",
    "owner_id": "uuid",
    "status": "string",
    "amount": "integer",
    "dept": "string",
    "flag": "boolean",
}
SUBJECT_ATTRS = ["id", "roles", "email", "tenant_id", "dept", "level"]
OWNER_A = uuid.UUID("00000000-0000-0000-0000-00000000000a")
OWNER_B = uuid.UUID("00000000-0000-0000-0000-00000000000b")


def pset(
    policies: dict[str, Any], attachments: dict[str, list[str]] | None = None, model: str = "pbac"
):  # noqa: ANN201
    return load_policy_set(
        {
            "model": model,
            "policies": policies,
            "attachments": attachments if attachments is not None else {"*": list(policies)},
            "field_types": {"Doc": DOC_FIELDS, "Note": {"id": "uuid", "title": "string"}},
            "subject_attributes": SUBJECT_ATTRS,
        }
    )


def ctx(roles: tuple[str, ...] = ("staff",), **attrs: Any) -> Context:
    subject = {"id": OWNER_A, "roles": roles, "tenant_id": None, "email": "a@x.io", **attrs}
    return Context(subject=subject, env={"hour_utc": 10, "weekday_utc": 2, "client_ip": "10.0.0.5"})


def leaf(left: dict, op: str, right: dict | None = None) -> dict:
    return {"left": left, "op": op, **({"right": right} if right is not None else {})}


R = lambda name: {"resource": name}  # noqa: E731
S = lambda name: {"subject": name}  # noqa: E731
E = lambda name: {"env": name}  # noqa: E731
L = lambda value: {"literal": value}  # noqa: E731


def allow(actions: list[str], when: dict | None = None) -> dict:
    return {"effect": "allow", "actions": actions, "when": when}


def deny(actions: list[str], when: dict | None = None) -> dict:
    return {"effect": "deny", "actions": actions, "when": when}


# -- decision table -------------------------------------------------------------------------


def test_default_deny_without_policies() -> None:
    d = decide(pset({}, {}), ctx(), "Doc", "list", {})
    assert not d.allowed and "default deny" in d.reason


def test_allow_policy_without_condition_allows_its_action_only() -> None:
    p = pset({"p": allow(["Doc.list"])})
    assert decide(p, ctx(), "Doc", "list", {}).allowed
    assert not decide(p, ctx(), "Doc", "delete", {}).allowed
    assert not decide(p, ctx(), "Note", "list", {}).allowed


def test_deny_overrides_allow() -> None:
    p = pset(
        {
            "all": allow(["Doc.*"]),
            "no_closed": deny(["Doc.update", "Doc.delete"], leaf(R("status"), "eq", L("closed"))),
        }
    )
    assert decide(p, ctx(), "Doc", "update", {"status": "open"}).allowed
    blocked = decide(p, ctx(), "Doc", "update", {"status": "closed"})
    assert not blocked.allowed and blocked.deny_matched == ("no_closed",)
    assert decide(
        p, ctx(), "Doc", "get", {"status": "closed"}
    ).allowed  # deny covers only update/delete


def test_conditions_must_hold_for_an_allow_to_apply() -> None:
    p = pset({"mine": allow(["Doc.get"], leaf(R("owner_id"), "eq", S("id")))})
    assert decide(p, ctx(), "Doc", "get", {"owner_id": OWNER_A}).allowed
    assert not decide(p, ctx(), "Doc", "get", {"owner_id": OWNER_B}).allowed
    assert not decide(p, ctx(), "Doc", "get", {}).allowed  # missing attribute: never allowed
    assert not decide(p, ctx(), "Doc", "get", {"owner_id": None}).allowed


def test_wildcard_actions() -> None:
    p = pset({"everything": allow(["*"]), "docs": allow(["Doc.*"])})
    assert decide(p, ctx(), "Note", "list", {}).allowed
    assert decide(pset({"docs": allow(["Doc.*"])}), ctx(), "Doc", "head", {}).allowed
    assert not decide(pset({"docs": allow(["Doc.*"])}), ctx(), "Note", "head", {}).allowed


def test_pbac_attaches_policies_by_role() -> None:
    p = pset(
        {"read": allow(["Doc.list", "Doc.get"]), "write": allow(["Doc.create", "Doc.update"])},
        {"*": ["read"], "editor": ["write"]},
    )
    assert decide(p, ctx(("viewer",)), "Doc", "list", {}).allowed
    assert not decide(p, ctx(("viewer",)), "Doc", "create", {}).allowed
    assert decide(p, ctx(("viewer", "editor")), "Doc", "create", {}).allowed
    assert not decide(p, ctx(()), "Doc", "create", {}).allowed


def test_abac_refuses_role_attachments() -> None:
    with pytest.raises(PolicyError, match="pbac"):
        pset({"p": allow(["*"])}, {"editor": ["p"]}, model="abac")


def test_role_conditions_in_abac_use_the_roles_attribute() -> None:
    is_admin = leaf(S("roles"), "contains", L("admin"))
    p = pset({"admins": allow(["Doc.delete"], is_admin)}, model="abac")
    assert decide(p, ctx(("admin",)), "Doc", "delete", {}).allowed
    assert not decide(p, ctx(("staff",)), "Doc", "delete", {}).allowed


@pytest.mark.parametrize(
    ("hour", "expected"), [(7, False), (8, True), (12, True), (17, True), (18, False), (23, False)]
)
def test_business_hours_window(hour: int, expected: bool) -> None:
    window = {"all": [leaf(E("hour_utc"), "gte", L(8)), leaf(E("hour_utc"), "lt", L(18))]}
    p = pset({"hours": allow(["Doc.update"], window)}, model="abac")
    c = Context(subject={"id": OWNER_A, "roles": ()}, env={"hour_utc": hour})
    assert decide(p, c, "Doc", "update", {}).allowed is expected


@pytest.mark.parametrize(
    ("ip", "expected"),
    [
        ("10.1.2.3", True),
        ("192.168.1.9", True),
        ("8.8.8.8", False),
        ("not-an-ip", False),
        (None, False),
        ("fd00::1", True),
    ],
)
def test_ip_allow_list(ip: str | None, expected: bool) -> None:
    rule = leaf(E("client_ip"), "ip_in", L(["10.0.0.0/8", "192.168.0.0/16", "fd00::/8"]))
    p = pset({"office": allow(["Doc.delete"], rule)}, model="abac")
    c = Context(subject={"id": OWNER_A, "roles": ()}, env={"client_ip": ip})
    assert decide(p, c, "Doc", "delete", {}).allowed is expected


def test_malformed_ip_list_never_matches() -> None:
    rule = leaf(E("client_ip"), "ip_in", L(["not-a-network"]))
    p = pset({"x": allow(["Doc.get"], rule)}, model="abac")
    assert not decide(p, ctx(), "Doc", "get", {}).allowed


@pytest.mark.parametrize(
    ("op", "row_value", "literal", "expected"),
    [
        ("eq", 5, 5, True),
        ("eq", 5, 6, False),
        ("ne", 5, 6, True),
        ("ne", None, 6, False),
        ("lt", 3, 5, True),
        ("lt", 5, 5, False),
        ("lte", 5, 5, True),
        ("gt", 6, 5, True),
        ("gte", 4, 5, False),
        ("gt", None, 5, False),
        ("eq", None, 5, False),
        ("eq", "5", 5, False),  # no silent type coercion between string and number
        ("lt", "abc", 5, False),  # incomparable types: False, not an exception
    ],
)
def test_comparison_semantics(op: str, row_value: Any, literal: Any, expected: bool) -> None:
    p = pset({"c": allow(["Doc.get"], leaf(R("amount"), op, L(literal)))})
    assert decide(p, ctx(), "Doc", "get", {"amount": row_value}).allowed is expected


def test_null_checks() -> None:
    p = pset({"n": allow(["Doc.get"], leaf(R("dept"), "is_null"))})
    assert decide(p, ctx(), "Doc", "get", {"dept": None}).allowed
    assert decide(p, ctx(), "Doc", "get", {}).allowed  # absent == null
    assert not decide(p, ctx(), "Doc", "get", {"dept": "x"}).allowed
    q = pset({"n": allow(["Doc.get"], leaf(R("dept"), "not_null"))})
    assert (
        decide(q, ctx(), "Doc", "get", {"dept": "x"}).allowed
        and not decide(q, ctx(), "Doc", "get", {}).allowed
    )


def test_in_and_not_in_with_none_in_the_list() -> None:
    p = pset({"i": allow(["Doc.get"], leaf(R("status"), "in", L(["open", None])))})
    assert decide(p, ctx(), "Doc", "get", {"status": "open"}).allowed
    assert not decide(p, ctx(), "Doc", "get", {"status": None}).allowed  # None never matches a list
    q = pset({"i": allow(["Doc.get"], leaf(R("status"), "not_in", L(["open"])))})
    assert decide(q, ctx(), "Doc", "get", {"status": "closed"}).allowed
    assert not decide(q, ctx(), "Doc", "get", {"status": None}).allowed  # NULL is not "not in"


def test_uuid_comparison_accepts_uuid_objects_and_strings() -> None:
    p = pset({"mine": allow(["Doc.get"], leaf(R("owner_id"), "eq", S("id")))})
    assert decide(p, ctx(), "Doc", "get", {"owner_id": str(OWNER_A)}).allowed
    lit = pset({"lit": allow(["Doc.get"], leaf(R("owner_id"), "eq", L(str(OWNER_A))))})
    assert decide(lit, ctx(), "Doc", "get", {"owner_id": OWNER_A}).allowed


def test_resource_in_subject_list() -> None:
    p = pset({"x": allow(["Doc.get"], leaf(R("dept"), "in", S("roles")))})
    assert decide(p, ctx(("sales", "staff")), "Doc", "get", {"dept": "sales"}).allowed
    assert not decide(p, ctx(("staff",)), "Doc", "get", {"dept": "sales"}).allowed


# -- the plan: what the generated routes use --------------------------------------------------------


def _col(name: str) -> sa.ColumnElement:
    return sa.column(name)


def test_plan_folds_subject_only_conditions() -> None:
    p = pset({"lvl": allow(["Doc.list"], leaf(S("level"), "gte", L(3)))})
    assert (
        plan(p, ctx(level=5), "Doc", "list", _col).row_filter is None
    )  # always true: no SQL at all
    refused = plan(p, ctx(level=1), "Doc", "list", _col)
    assert not refused.allowed and refused.row_filter is None
    assert not plan(p, ctx(), "Doc", "list", _col).allowed  # attribute missing: refused


def test_plan_refuses_without_any_allow_policy() -> None:
    p = pset({"only_deny": deny(["Doc.list"])})
    assert not plan(p, ctx(), "Doc", "list", _col).allowed


def test_plan_unconditional_deny_wins_even_over_unrestricted_allow() -> None:
    p = pset({"a": allow(["Doc.*"]), "d": deny(["Doc.delete"])})
    refused = plan(p, ctx(), "Doc", "delete", _col)
    assert not refused.allowed and refused.deny_ids == ("d",)
    assert plan(p, ctx(), "Doc", "get", _col).allowed


def test_plan_row_filter_contains_the_row_condition_only() -> None:
    p = pset({"mine": allow(["Doc.list"], leaf(R("owner_id"), "eq", S("id")))})
    result = plan(p, ctx(), "Doc", "list", _col)
    assert result.allowed and result.row_filter is not None
    assert result.check_row({"owner_id": OWNER_A}) and not result.check_row({"owner_id": OWNER_B})


# -- hostile policy data ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "when",
    [
        {"all": []},
        {"all": "x"},
        {
            "any": [{"all": [{"any": [{"all": [{"any": [leaf(R("status"), "eq", L("a"))]}]}]}]}]
        },  # too deep
        {"left": R("status"), "op": "eval", "right": L("1")},  # no such operator
        {"left": {"resource": "status", "x": 1}, "op": "eq", "right": L(1)},
        {"left": {"python": "__import__('os')"}, "op": "eq", "right": L(1)},
        {"left": R("status"), "op": "eq"},  # missing right
        {"left": R("status"), "op": "is_null", "right": L(1)},  # unary with right
        {"left": R("status"), "op": "eq", "right": L(1), "extra": 1},
        {"not": leaf(R("status"), "eq", L(1))},  # no negation operator exists
        "status == 'open'",  # an expression string is not a condition
        [leaf(R("status"), "eq", L(1))],
    ],
)
def test_malformed_conditions_are_refused_at_load(when: Any) -> None:
    with pytest.raises(PolicyError):
        pset({"p": allow(["Doc.get"], when)})


@pytest.mark.parametrize(
    "operand",
    [
        S("__class__"),
        S("password_hash"),
        S("roles; DROP TABLE users"),
        R("__dict__"),
        R("secret_column"),
        R("status') OR ('1'='1"),
        E("os_environ"),
        E("hour_utc; 1"),
    ],
)
def test_unknown_attributes_are_refused_at_load(operand: dict) -> None:
    with pytest.raises(PolicyError, match="unknown|has no attribute"):
        pset({"p": allow(["Doc.get"], leaf(operand, "eq", L(1)))})


def test_attachments_must_name_existing_policies() -> None:
    with pytest.raises(PolicyError, match="unknown policies"):
        pset({"p": allow(["*"])}, {"*": ["ghost"]})


def test_oversized_inputs_are_refused() -> None:
    big = {"all": [leaf(R("amount"), "eq", L(i)) for i in range(eng.MAX_NODES + 1)]}
    with pytest.raises(PolicyError, match="too deep or too large"):
        pset({"p": allow(["Doc.get"], big)})
    with pytest.raises(PolicyError, match="more than"):
        pset(
            {
                "p": allow(
                    ["Doc.get"], leaf(R("status"), "in", L(["x"] * (eng.MAX_LIST_LITERAL + 1)))
                )
            }
        )
    with pytest.raises(PolicyError, match="at most"):
        pset({f"p{i}": allow(["*"]) for i in range(eng.MAX_POLICIES + 1)})


def test_effect_and_actions_are_checked() -> None:
    for bad in (
        {"effect": "maybe", "actions": ["*"]},
        {"effect": "allow", "actions": []},
        {"effect": "allow", "actions": [1]},
    ):
        with pytest.raises(PolicyError):
            pset({"p": bad})
    with pytest.raises(PolicyError, match="model"):
        load_policy_set({"model": "rbac", "policies": {}})


def test_policy_data_round_trips_through_json() -> None:
    raw = {
        "p": allow(
            ["Doc.get"],
            {"any": [leaf(R("status"), "in", L(["a", "b"])), leaf(R("amount"), "gt", L(1))]},
        )
    }
    assert (
        pset(json.loads(json.dumps(raw))).policies["p"]["when"] == pset(raw).policies["p"]["when"]
    )


# -- SQL == Python == reference -----------------------------------------------------------------------


def ref_value(operand: dict, subject: dict, env: dict, row: dict) -> Any:
    ((kind, name),) = operand.items()
    value = {
        "literal": lambda: name,
        "subject": lambda: subject.get(name),
        "env": lambda: env.get(name),
        "resource": lambda: row.get(name),
    }[kind]()
    return str(value) if isinstance(value, uuid.UUID) else value


def ref_leaf(node: dict, subject: dict, env: dict, row: dict) -> bool:
    op = node["op"]
    a = ref_value(node["left"], subject, env, row)
    if op == "is_null":
        return a is None
    if op == "not_null":
        return a is not None
    b = ref_value(node["right"], subject, env, row)
    if op == "contains":
        a, b, op = b, a, "in"
    if op == "ip_in":
        import ipaddress

        return a is not None and any(ipaddress.ip_address(a) in ipaddress.ip_network(n) for n in b)
    if a is None or b is None:
        return False
    if op in ("in", "not_in"):
        members = [str(x) if isinstance(x, uuid.UUID) else x for x in b if x is not None]
        return (a in members) if op == "in" else (a not in members)
    return {"eq": a == b, "ne": a != b, "lt": a < b, "lte": a <= b, "gt": a > b, "gte": a >= b}[op]


def ref_node(node: dict, subject: dict, env: dict, row: dict) -> bool:
    if "all" in node:
        return all(ref_node(c, subject, env, row) for c in node["all"])
    if "any" in node:
        return any(ref_node(c, subject, env, row) for c in node["any"])
    return ref_leaf(node, subject, env, row)


def ref_allowed(raw: dict, subject: dict, env: dict, entity: str, op: str, row: dict) -> bool:
    ids = list(raw["attachments"].get("*", []))
    for role in sorted(set(subject["roles"])):
        ids += raw["attachments"].get(role, [])
    allowed = denied = False
    for pid in dict.fromkeys(ids):
        pol = raw["policies"][pid]
        if not any(a in ("*", f"{entity}.{op}", f"{entity}.*") for a in pol["actions"]):
            continue
        hit = pol["when"] is None or ref_node(pol["when"], subject, env, row)
        if hit and pol["effect"] == "allow":
            allowed = True
        if hit and pol["effect"] == "deny":
            denied = True
    return allowed and not denied


RESOURCE_LEAVES = [
    lambda r: leaf(R("status"), "eq", L(r.choice(["draft", "open", "closed"]))),
    lambda r: leaf(
        R("status"), "in", L(r.sample(["draft", "open", "closed", "x"], r.randint(1, 3)))
    ),
    lambda r: leaf(
        R("status"), "not_in", L(r.sample(["draft", "open", "closed"], r.randint(1, 2)))
    ),
    lambda r: leaf(
        R("amount"), r.choice(["lt", "lte", "gt", "gte", "eq", "ne"]), L(r.randint(0, 6))
    ),
    lambda r: leaf(R("owner_id"), "eq", S("id")),
    lambda r: leaf(R("owner_id"), "ne", S("id")),
    lambda r: leaf(R("owner_id"), "eq", L(str(r.choice([OWNER_A, OWNER_B])))),
    lambda r: leaf(R("dept"), "eq", S("dept")),
    lambda r: leaf(R("dept"), "in", S("roles")),
    lambda r: leaf(R("flag"), "eq", L(r.choice([True, False]))),
    lambda r: leaf(R("dept"), "is_null"),
    lambda r: leaf(R("amount"), "not_null"),
    lambda r: leaf(R("status"), "eq", R("dept")),
]
CONSTANT_LEAVES = [
    lambda r: leaf(S("level"), "gte", L(r.randint(0, 5))),
    lambda r: leaf(E("hour_utc"), "lt", L(r.randint(0, 24))),
    lambda r: leaf(S("roles"), "contains", L(r.choice(["admin", "staff", "guest"]))),
    lambda r: leaf(E("client_ip"), "ip_in", L(["10.0.0.0/8", "172.16.0.0/12"])),
    lambda r: leaf(S("dept"), "eq", L(r.choice(["a", "b"]))),
]


def random_node(r: random.Random, depth: int = 0) -> dict:
    if depth >= 2 or r.random() < 0.45:
        pool = RESOURCE_LEAVES if r.random() < 0.75 else CONSTANT_LEAVES
        return r.choice(pool)(r)
    return {r.choice(["all", "any"]): [random_node(r, depth + 1) for _ in range(r.randint(1, 3))]}


def random_policy_raw(r: random.Random) -> dict:
    policies = {}
    for i in range(r.randint(1, 5)):
        policies[f"p{i}"] = {
            "effect": r.choice(["allow", "allow", "deny"]),
            "actions": [r.choice(["Doc.list", "Doc.*", "*"])],
            "when": None if r.random() < 0.15 else random_node(r),
        }
    attachments: dict[str, list[str]] = {"*": [], "admin": [], "staff": []}
    for pid in policies:
        attachments[r.choice(["*", "*", "admin", "staff"])].append(pid)
    return {
        "model": "pbac",
        "policies": policies,
        "attachments": attachments,
        "field_types": {"Doc": DOC_FIELDS},
        "subject_attributes": SUBJECT_ATTRS,
    }


def random_rows(r: random.Random, n: int = 40) -> list[dict]:
    pick = lambda options: r.choice([*options, None])  # noqa: E731
    return [
        {
            "id": uuid.UUID(int=i + 1),
            "owner_id": pick([OWNER_A, OWNER_B]),
            "status": pick(["draft", "open", "closed", "x"]),
            "amount": pick(range(0, 7)),
            "dept": pick(["a", "b", "sales", "staff"]),
            "flag": pick([True, False]),
        }
        for i in range(n)
    ]


def test_sql_python_and_reference_agree_on_random_policies() -> None:
    engine = sa.create_engine("sqlite://")
    meta = sa.MetaData()
    table = sa.Table(
        "docs",
        meta,
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("owner_id", sa.Uuid, nullable=True),
        sa.Column("status", sa.String, nullable=True),
        sa.Column("amount", sa.Integer, nullable=True),
        sa.Column("dept", sa.String, nullable=True),
        sa.Column("flag", sa.Boolean, nullable=True),
    )
    meta.create_all(engine)
    rng = random.Random(20261024)
    rows = random_rows(rng)
    with engine.begin() as conn:
        conn.execute(table.insert(), rows)

    checked_filters = 0
    for case in range(500):
        raw = random_policy_raw(rng)
        policy_set = load_policy_set(raw)
        subject = {
            "id": rng.choice([OWNER_A, OWNER_B]),
            "roles": tuple(rng.sample(["admin", "staff", "guest"], rng.randint(0, 3))),
            "dept": rng.choice(["a", "b", "sales", None]),
            "level": rng.choice([0, 2, 5, None]),
            "email": "x@x.io",
            "tenant_id": None,
        }
        env = {
            "hour_utc": rng.randint(0, 23),
            "client_ip": rng.choice(["10.2.3.4", "8.8.8.8", None]),
        }
        context = Context(subject=subject, env=env)
        p = plan(policy_set, context, "Doc", "list", lambda name: table.c[name])

        expected = {row["id"] for row in rows if ref_allowed(raw, subject, env, "Doc", "list", row)}
        python = {row["id"] for row in rows if p.check_row(row)}
        assert python == expected, f"python check disagrees with reference (case {case}): {raw}"
        if not p.allowed:
            assert expected == set(), f"refused outright but reference allows rows (case {case})"
            continue
        stmt = sa.select(table.c.id)
        if p.row_filter is not None:
            stmt = stmt.where(p.row_filter)
            checked_filters += 1
        with engine.connect() as conn:
            via_sql = {row[0] for row in conn.execute(stmt)}
        assert via_sql == expected, f"SQL filter disagrees with reference (case {case}): {raw}"
    assert checked_filters > 100  # the generator really exercised row filters, not just constants


def test_literals_are_bound_parameters_not_sql() -> None:
    engine = sa.create_engine("sqlite://")
    meta = sa.MetaData()
    table = sa.Table(
        "docs", meta, sa.Column("id", sa.Integer, primary_key=True), sa.Column("status", sa.String)
    )
    meta.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            table.insert(), [{"id": 1, "status": "open"}, {"id": 2, "status": "x' OR '1'='1"}]
        )
    nasty = "x' OR '1'='1"
    p = load_policy_set(
        {
            "model": "pbac",
            "policies": {"p": allow(["Doc.list"], leaf(R("status"), "eq", L(nasty)))},
            "attachments": {"*": ["p"]},
            "field_types": {"Doc": {"status": "string"}},
        }
    )
    result = plan(p, Context(subject={"id": 1, "roles": ()}), "Doc", "list", lambda n: table.c[n])
    with engine.connect() as conn:
        assert [r[0] for r in conn.execute(sa.select(table.c.id).where(result.row_filter))] == [
            2
        ]  # exactly the literal
