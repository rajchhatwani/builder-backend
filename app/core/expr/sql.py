"""Postgres emitter: typed AST -> SQL text. Identifiers come only from the schema (quoted by one
function); literals are rendered by typed emitters (never by pasting user text).

`SQL_SCHEMA` creates the `expr` helper schema that generated projects install once.
"""

import re

from app.core.expr.errors import ExprError
from app.core.expr.parser import Node
from app.core.expr.scope import SETTING_PREFIX

# Multiply by 0.0000000001, never divide by 10^10: numeric division keeps only ~16 significant digits.
SQL_SCHEMA = """\
CREATE SCHEMA IF NOT EXISTS expr;
CREATE OR REPLACE FUNCTION expr.div_dec(a numeric, b numeric) RETURNS numeric
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE WHEN a IS NULL OR b IS NULL OR b = 0 THEN NULL
    ELSE (u.q + CASE WHEN 2 * abs(u.r) >= abs(b) THEN sign(a) * sign(b) ELSE 0 END) * 0.0000000001 END
  FROM (SELECT t.q, a * 10000000000 - t.q * b AS r
        FROM (SELECT div(a * 10000000000, NULLIF(b, 0)) AS q) t) u
$$;
"""

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DECIMAL = re.compile(r"^\d+(\.\d+)?$")


def quote_ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ExprError(f"bad identifier {name!r}")
    return '"' + name + '"'


def _string(value: str) -> str:
    if "\x00" in value:
        raise ExprError("NUL in string")
    return "'" + value.replace("'", "''") + "'"  # standard_conforming_strings: no backslash escapes


def _lit(n: Node) -> str:
    t, v = n["t"], n["v"]
    if t == "bool":
        return "TRUE" if v else "FALSE"
    if t == "int":
        return f"({int(v)}::bigint)"
    if t == "decimal":
        if not _DECIMAL.match(v):
            raise ExprError("bad decimal literal")
        return f"({v}::numeric)"
    return f"({_string(v)}::text)"


def _num(sql: str, from_t: str, to_t: str) -> str:
    return f"({sql}::numeric)" if from_t == "int" and to_t == "decimal" else sql


def to_sql(node: Node) -> str:
    k = node["k"]
    if k == "lit":
        return _lit(node)
    if k == "field":
        if node["name"].startswith(SETTING_PREFIX):
            raise ExprError(
                "settings cannot be used in SQL expressions: they are read at run time by the application"
            )
        return quote_ident(node["name"])
    if k == "un":
        x = to_sql(node["x"])
        return f"(NOT {x})" if node["op"] == "not" else f"(-{x})"
    if k == "in":
        x = to_sql(node["x"])
        xt = node["x"]["t"]
        items = ", ".join(
            _lit(i) if i["t"] == xt or xt == "string" or xt == "bool" else f"({i['v']}::numeric)"
            for i in node["items"]
        )
        if xt == "int" and any(i["t"] == "decimal" for i in node["items"]):
            x = f"({x}::numeric)"
        return f"({x} IN ({items}))"
    if k == "bin":
        return _binary(node)
    if k == "call":
        return _call(node)
    raise ExprError(f"cannot emit node {k!r}")


def _binary(n: Node) -> str:
    op, lt, rt_ = n["op"], n["l"]["t"], n["r"]["t"]
    left, right = to_sql(n["l"]), to_sql(n["r"])
    if op in ("and", "or"):
        return f"({left} {op.upper()} {right})"
    if op in ("==", "!=", "<", "<=", ">", ">="):
        sql_op = {"==": "=", "!=": "<>"}.get(op, op)
        if lt == "string":
            return f'({left} COLLATE "C" {sql_op} {right} COLLATE "C")'
        if "decimal" in (lt, rt_):
            left, right = _num(left, lt, "decimal"), _num(right, rt_, "decimal")
        return f"({left} {sql_op} {right})"
    if op == "%":
        return f"({left} % NULLIF({right}, 0))"
    if op == "/":
        return f"expr.div_dec({_num(left, lt, 'decimal')}, {_num(right, rt_, 'decimal')})"
    if n["t"] == "decimal":
        left, right = _num(left, lt, "decimal"), _num(right, rt_, "decimal")
    return f"({left} {op} {right})"


def _call(n: Node) -> str:
    fn = n["fn"]
    args = [to_sql(a) for a in n["args"]]
    types = [a["t"] for a in n["args"]]
    if fn == "isnull":
        return f"({args[0]} IS NULL)"
    if fn == "coalesce":
        wide = [_num(a, t, n["t"]) for a, t in zip(args, types, strict=True)]
        return f"COALESCE({', '.join(wide)})"
    if fn == "abs":
        return f"abs({args[0]})"
    if fn == "round":
        return f"round({_num(args[0], types[0], 'decimal')}, {int(n['args'][1]['v'])})"
    if fn == "div":
        return f"({args[0]} / NULLIF({args[1]}, 0))"
    if fn == "length":
        return f"char_length({args[0]})"
    raise ExprError(f"cannot emit function {fn!r}")
