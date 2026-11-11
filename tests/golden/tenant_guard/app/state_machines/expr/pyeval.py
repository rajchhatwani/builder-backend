"""Compile a typed AST into a Python closure `row -> value`. No eval, no exec, no getattr tricks:
the closure tree is built from the AST node by node and only calls functions of runtime.py.
Row values: bool, int, Decimal, str or None, looked up by field name in a dict.
"""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from app.state_machines.expr import runtime as rt
from app.state_machines.expr.errors import ExprError
from app.state_machines.expr.parser import Node

Row = dict[str, Any]
Fn = Callable[[Row], Any]


def _widen(f: Fn, from_t: str, to_t: str) -> Fn:
    if from_t == "int" and to_t == "decimal":
        return lambda row: rt.to_decimal(f(row))
    return f


def compile_python(node: Node) -> Fn:
    """`node` must come from check(). Raises ExprError for an unchecked or unknown node."""
    k = node["k"]
    if k == "lit":
        value: Any = Decimal(node["v"]) if node["t"] == "decimal" else node["v"]
        return lambda row: value
    if k == "field":
        name, t = node["name"], node["t"]

        def field(row: Row) -> Any:
            v = row.get(name)
            return Decimal(v) if t == "decimal" and v is not None and not isinstance(v, Decimal) else v

        return field
    if k == "un":
        x = compile_python(node["x"])
        if node["op"] == "not":
            return lambda row: rt.not3(x(row))
        neg = rt.ineg if node["t"] == "int" else rt.dneg
        return lambda row: neg(x(row))
    if k == "bin":
        return _binary(node)
    if k == "in":
        xt = node["x"]["t"]
        x = _widen(compile_python(node["x"]), xt, "decimal" if xt == "decimal" else xt)
        items = [Decimal(i["v"]) if i["t"] == "decimal" else i["v"] for i in node["items"]]
        return lambda row: rt.in_list(x(row), items)
    if k == "call":
        return _call(node)
    raise ExprError(f"cannot compile node {k!r}")


def _binary(node: Node) -> Fn:
    op, lt, rt_ = node["op"], node["l"]["t"], node["r"]["t"]
    left, right = compile_python(node["l"]), compile_python(node["r"])
    if op == "and":
        return lambda row: rt.and3(left(row), right(row))
    if op == "or":
        return lambda row: rt.or3(left(row), right(row))
    if op in ("==", "!=", "<", "<=", ">", ">="):
        return lambda row: rt.compare(op, left(row), right(row))
    if op == "%":
        return lambda row: rt.imod(left(row), right(row))
    if op == "/":
        a, b = _widen(left, lt, "decimal"), _widen(right, rt_, "decimal")
        return lambda row: rt.ddiv(a(row), b(row))
    if node["t"] == "int":
        fn = {"+": rt.iadd, "-": rt.isub, "*": rt.imul}[op]
        return lambda row: fn(left(row), right(row))
    a, b = _widen(left, lt, "decimal"), _widen(right, rt_, "decimal")
    dfn = {"+": rt.dadd, "-": rt.dsub, "*": rt.dmul}[op]
    return lambda row: dfn(a(row), b(row))


def _call(node: Node) -> Fn:
    fn = node["fn"]
    args = [compile_python(a) for a in node["args"]]
    if fn == "isnull":
        return lambda row: args[0](row) is None
    if fn == "coalesce":
        target = node["t"]
        wide = [_widen(a, n["t"], target) for a, n in zip(args, node["args"], strict=True)]
        return lambda row: rt.coalesce(*[w(row) for w in wide])
    if fn == "abs":
        f = rt.iabs if node["t"] == "int" else rt.dabs
        return lambda row: f(args[0](row))
    if fn == "round":
        digits = node["args"][1]["v"]
        x = _widen(args[0], node["args"][0]["t"], "decimal")
        return lambda row: rt.dround(x(row), digits)
    if fn == "div":
        return lambda row: rt.idiv(args[0](row), args[1](row))
    if fn == "length":
        return lambda row: None if (s := args[0](row)) is None else len(s)
    raise ExprError(f"cannot compile function {fn!r}")
