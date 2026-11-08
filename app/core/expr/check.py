"""Type checker: AST + entity fields -> typed AST (every node gets "t" and "nullable").

Types: bool, int (int64), decimal, string. int widens to decimal; nothing else converts implicitly.
`/` needs at least one decimal (int / int is an error: use div(a, b)). There is no null literal.
"""

import re
from typing import Any

from app.core.expr.errors import ExprError
from app.core.expr.parser import Node

# field name -> (type, nullable)
Schema = dict[str, tuple[str, bool]]

TYPES = ("bool", "int", "decimal", "string")
_NUMERIC = ("int", "decimal")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _numeric_join(a: str, b: str) -> str:
    return "decimal" if "decimal" in (a, b) else "int"


def _need(node: Node, got: str, wanted: tuple[str, ...], what: str) -> None:
    if got not in wanted:
        raise ExprError(f"{what} needs {' or '.join(wanted)}, got {got}", node.get("pos", 0))


def check(node: Node, schema: Schema) -> Node:
    """Return a typed copy of `node`. Raises ExprError with a position on any problem."""
    for name, (ftype, _) in schema.items():
        if ftype not in TYPES or not _IDENT.match(name):
            raise ExprError(f"bad schema entry {name!r}")
    return _check(node, schema)


def _check(n: Node, schema: Schema) -> Node:
    pos = n.get("pos", 0)
    k = n["k"]
    out: Node = dict(n)
    if k == "lit":
        out["t"], out["nullable"] = n["t"], False
    elif k == "field":
        entry = schema.get(n["name"])
        if entry is None:
            known = ", ".join(sorted(schema)) or "none"
            raise ExprError(f"unknown field {n['name']!r}; known fields: {known}", pos)
        out["t"], out["nullable"] = entry
    elif k == "un":
        x = _check(n["x"], schema)
        out["x"] = x
        if n["op"] == "not":
            _need(n, x["t"], ("bool",), "'not'")
            out["t"] = "bool"
        else:
            _need(n, x["t"], _NUMERIC, "unary '-'")
            out["t"] = x["t"]
        out["nullable"] = x["nullable"]
    elif k == "bin":
        out["l"], out["r"] = _check(n["l"], schema), _check(n["r"], schema)
        out["t"] = _bin_type(n, out["l"]["t"], out["r"]["t"])
        out["nullable"] = out["l"]["nullable"] or out["r"]["nullable"] or n["op"] in ("/", "%")
    elif k == "in":
        x = _check(n["x"], schema)
        items = [_check(i, schema) for i in n["items"]]
        for item in items:
            if item["k"] != "lit":
                raise ExprError("a list may only contain literal values", int(item.get("pos", 0)))
            if not _comparable(x["t"], item["t"]):
                raise ExprError(f"cannot compare {x['t']} with {item['t']}", int(item.get("pos", 0)))
        out.update(x=x, items=items, t="bool", nullable=x["nullable"])
    elif k == "call":
        args = [_check(a, schema) for a in n["args"]]
        out["args"] = args
        out["t"], out["nullable"] = _call_type(n, args)
    else:
        raise ExprError(f"unknown node kind {k!r}", pos)
    return out


def _comparable(a: str, b: str) -> bool:
    return a == b or (a in _NUMERIC and b in _NUMERIC)


def _bin_type(n: Node, a: str, b: str) -> str:
    op = n["op"]
    if op in ("and", "or"):
        _need(n, a, ("bool",), f"'{op}'")
        _need(n, b, ("bool",), f"'{op}'")
        return "bool"
    if op in ("==", "!="):
        if not _comparable(a, b):
            raise ExprError(f"cannot compare {a} with {b}", n["pos"])
        return "bool"
    if op in ("<", "<=", ">", ">="):
        if not _comparable(a, b) or a == "bool":
            raise ExprError(f"cannot order {a} and {b}", n["pos"])
        return "bool"
    _need(n, a, _NUMERIC, f"'{op}'")
    _need(n, b, _NUMERIC, f"'{op}'")
    if op == "%":
        if (a, b) != ("int", "int"):
            raise ExprError("'%' needs two integers", n["pos"])
        return "int"
    if op == "/":
        if (a, b) == ("int", "int"):
            raise ExprError("int / int is not allowed; use div(a, b) or make one side decimal", n["pos"])
        return "decimal"
    return _numeric_join(a, b)


def _call_type(n: Node, args: list[Node]) -> tuple[str, bool]:
    fn, pos = n["fn"], n.get("pos", 0)
    types = [a["t"] for a in args]

    def arity(count: int) -> None:
        if len(args) != count:
            raise ExprError(f"{fn}() takes {count} argument(s), got {len(args)}", pos)

    if fn == "isnull":
        arity(1)
        return "bool", False
    if fn == "coalesce":
        if len(args) < 2:
            raise ExprError("coalesce() needs at least two arguments", pos)
        joined = types[0]
        for t in types[1:]:
            if t == joined:
                continue
            if t in _NUMERIC and joined in _NUMERIC:
                joined = "decimal"
            else:
                raise ExprError(f"coalesce() arguments differ: {joined} and {t}", pos)
        return joined, all(a["nullable"] for a in args)
    if fn == "abs":
        arity(1)
        _need(n, types[0], _NUMERIC, "abs()")
        return types[0], args[0]["nullable"]
    if fn == "round":
        arity(2)
        _need(n, types[0], _NUMERIC, "round()")
        digits = args[1]
        if digits["k"] != "lit" or digits["t"] != "int" or not 0 <= digits["v"] <= 10:
            raise ExprError("round() digits must be an integer literal from 0 to 10", pos)
        return "decimal", args[0]["nullable"]
    if fn == "div":
        arity(2)
        _need(n, types[0], ("int",), "div()")
        _need(n, types[1], ("int",), "div()")
        return "int", True
    if fn == "length":
        arity(1)
        _need(n, types[0], ("string",), "length()")
        return "int", args[0]["nullable"]
    raise ExprError(f"unknown function {fn!r}; available: abs, coalesce, div, isnull, length, round", pos)


def result_type(typed: Node) -> dict[str, Any]:
    return {"type": typed["t"], "nullable": typed["nullable"]}
