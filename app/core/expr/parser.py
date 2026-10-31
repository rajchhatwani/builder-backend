"""Hand-written Pratt parser: text -> canonical JSON AST. Never evaluates anything.

Grammar (lowest to highest precedence): or | and | not | comparison / in | + - | * / % | unary - | primary.
`and`/`or`/`not` and `&&`/`||`/`!` are the same operators. Nodes are plain dicts:
  {"k":"lit","t":"int|decimal|string|bool","v":...}   decimals and ints are stored as strings/ints
  {"k":"field","name":...}  {"k":"un","op":"-|not","x":...}  {"k":"bin","op":...,"l":...,"r":...}
  {"k":"in","x":...,"items":[...]}  {"k":"call","fn":...,"args":[...]}
Each node carries "pos" (character offset); `canonical()` strips it for storage.
"""

import re
from typing import Any

from app.core.expr.errors import ExprError
from app.core.expr.limits import (
    INT64_MAX,
    MAX_DECIMAL_DIGITS,
    MAX_DEPTH,
    MAX_LIST_ITEMS,
    MAX_NODES,
    MAX_SOURCE_CHARS,
    MAX_STRING_CHARS,
)

Node = dict[str, Any]

_TOKEN = re.compile(
    r"""\s*(?:
    (?P<num>\d+(?:\.\d+)?)
  | (?P<id>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<str>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")
  | (?P<op>==|!=|<=|>=|&&|\|\||[-+*/%<>!(),\[\]])
    )""",
    re.VERBOSE,
)
_ESCAPES = {"\\": "\\", "'": "'", '"': '"', "n": "\n", "t": "\t"}
_COMPARE = {"==", "!=", "<", "<=", ">", ">="}


def _tokens(src: str) -> list[tuple[str, str, int]]:
    out: list[tuple[str, str, int]] = []
    i = 0
    while True:
        while i < len(src) and src[i].isspace():
            i += 1
        if i >= len(src):
            out.append(("end", "", i))
            return out
        m = _TOKEN.match(src, i)
        if not m or m.end() == i:
            raise ExprError(f"unexpected character {src[i]!r}", i)
        start = m.start(m.lastgroup or 0)
        kind = m.lastgroup or ""
        out.append((kind, m.group(kind), start))
        i = m.end()


class _Parser:
    def __init__(self, src: str) -> None:
        self.toks = _tokens(src)
        self.i = 0
        self.nodes = 0
        self.depth = 0

    # --- helpers
    def peek(self) -> tuple[str, str, int]:
        return self.toks[self.i]

    def take(self) -> tuple[str, str, int]:
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def is_op(self, *ops: str) -> bool:
        kind, text, _ = self.peek()
        return (kind == "op" and text in ops) or (kind == "id" and text in ops)

    def expect(self, op: str) -> None:
        if not self.is_op(op):
            raise ExprError(f"expected {op!r}", self.peek()[2])
        self.take()

    def node(self, n: Node) -> Node:
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise ExprError(f"expression is too large (more than {MAX_NODES} parts)", n["pos"])
        return n

    def enter(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ExprError(f"expression is nested too deeply (more than {MAX_DEPTH} levels)", self.peek()[2])

    def leave(self) -> None:
        self.depth -= 1

    # --- grammar
    def parse(self) -> Node:
        tree = self.or_()
        if self.peek()[0] != "end":
            raise ExprError(f"unexpected {self.peek()[1]!r}", self.peek()[2])
        return tree

    def or_(self) -> Node:
        self.enter()
        left = self.and_()
        while self.is_op("or", "||"):
            pos = self.take()[2]
            left = self.node({"k": "bin", "op": "or", "l": left, "r": self.and_(), "pos": pos})
        self.leave()
        return left

    def and_(self) -> Node:
        left = self.not_()
        while self.is_op("and", "&&"):
            pos = self.take()[2]
            left = self.node({"k": "bin", "op": "and", "l": left, "r": self.not_(), "pos": pos})
        return left

    def not_(self) -> Node:
        if self.is_op("not", "!"):
            self.enter()
            pos = self.take()[2]
            x = self.not_()
            self.leave()
            return self.node({"k": "un", "op": "not", "x": x, "pos": pos})
        return self.cmp()

    def cmp(self) -> Node:
        left = self.add()
        if self.peek()[0] == "op" and self.peek()[1] in _COMPARE:
            kind, op, pos = self.take()
            return self.node({"k": "bin", "op": op, "l": left, "r": self.add(), "pos": pos})
        if self.is_op("in"):
            pos = self.take()[2]
            self.expect("[")
            items = [self.add()]
            while self.is_op(","):
                self.take()
                items.append(self.add())
                if len(items) > MAX_LIST_ITEMS:
                    raise ExprError(f"a list may have at most {MAX_LIST_ITEMS} items", pos)
            self.expect("]")
            return self.node({"k": "in", "x": left, "items": items, "pos": pos})
        return left

    def add(self) -> Node:
        left = self.mul()
        while self.peek()[0] == "op" and self.peek()[1] in ("+", "-"):
            _, op, pos = self.take()
            left = self.node({"k": "bin", "op": op, "l": left, "r": self.mul(), "pos": pos})
        return left

    def mul(self) -> Node:
        left = self.unary()
        while self.peek()[0] == "op" and self.peek()[1] in ("*", "/", "%"):
            _, op, pos = self.take()
            left = self.node({"k": "bin", "op": op, "l": left, "r": self.unary(), "pos": pos})
        return left

    def unary(self) -> Node:
        if self.peek()[0] == "op" and self.peek()[1] == "-":
            self.enter()
            pos = self.take()[2]
            x = self.unary()
            self.leave()
            return self.node({"k": "un", "op": "-", "x": x, "pos": pos})
        return self.primary()

    def primary(self) -> Node:
        kind, text, pos = self.take()
        if kind == "num":
            if "." in text:
                digits = len(text.replace(".", "").lstrip("0")) or 1
                if digits > MAX_DECIMAL_DIGITS:
                    raise ExprError(f"a decimal may have at most {MAX_DECIMAL_DIGITS} digits", pos)
                return self.node({"k": "lit", "t": "decimal", "v": text, "pos": pos})
            if int(text) > INT64_MAX:
                raise ExprError("integer does not fit in 64 bits", pos)
            return self.node({"k": "lit", "t": "int", "v": int(text), "pos": pos})
        if kind == "str":
            body = _unescape(text[1:-1], pos)
            if len(body) > MAX_STRING_CHARS:
                raise ExprError(f"a string may have at most {MAX_STRING_CHARS} characters", pos)
            return self.node({"k": "lit", "t": "string", "v": body, "pos": pos})
        if kind == "id":
            if text in ("true", "false"):
                return self.node({"k": "lit", "t": "bool", "v": text == "true", "pos": pos})
            if text == "null":
                raise ExprError("there is no null literal; use isnull(x) or coalesce(x, default)", pos)
            if text in ("and", "or", "not", "in"):
                raise ExprError(f"unexpected {text!r}", pos)
            if self.is_op("("):
                self.take()
                self.enter()
                args: list[Node] = []
                if not self.is_op(")"):
                    args.append(self.or_())
                    while self.is_op(","):
                        self.take()
                        args.append(self.or_())
                self.leave()
                self.expect(")")
                return self.node({"k": "call", "fn": text, "args": args, "pos": pos})
            return self.node({"k": "field", "name": text, "pos": pos})
        if kind == "op" and text == "(":
            inner = self.or_()
            self.expect(")")
            return inner
        raise ExprError("expected a value" if kind != "end" else "expression ends too early", pos)


def _unescape(body: str, pos: int) -> str:
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            i += 1
            if body[i] not in _ESCAPES:
                raise ExprError(f"unknown escape \\{body[i]}", pos + i)
            out.append(_ESCAPES[body[i]])
        else:
            out.append(ch)
        i += 1
    text = "".join(out)
    if "\x00" in text:
        raise ExprError("a string may not contain a NUL character", pos)
    return text


def parse(src: str) -> Node:
    """Parse expression text. Raises ExprError (never anything else) on bad input."""
    if not isinstance(src, str):
        raise ExprError("expression must be text")
    if len(src) > MAX_SOURCE_CHARS:
        raise ExprError(f"expression is longer than {MAX_SOURCE_CHARS} characters")
    if not src.strip():
        raise ExprError("expression is empty")
    return _Parser(src).parse()


def canonical(node: Node) -> Node:
    """The stored form: the AST without positions, keys in a fixed order."""
    out: Node = {}
    for key in sorted(node):
        if key == "pos":
            continue
        value = node[key]
        if isinstance(value, dict):
            out[key] = canonical(value)
        elif isinstance(value, list):
            out[key] = [canonical(v) for v in value]
        else:
            out[key] = value
    return out
