"""B1-3: parser, checker, evaluator semantics, safety limits, fuzzing, no eval."""

import random
import re
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.expr import ExprError, ExprOverflow, canonical, check, compile_python, parse, to_sql
from app.core.expr.limits import MAX_DEPTH, MAX_NODES, MAX_SOURCE_CHARS
from tests.expr_gen import SCHEMA, gen, make_rows

S = {"a": ("int", True), "x": ("decimal", True), "s": ("string", True), "ok": ("bool", True)}


def ev(text: str, **row: object) -> object:
    return compile_python(check(parse(text), S))(row)


def test_aliases_store_one_canonical_form() -> None:
    assert canonical(parse("ok and not ok or ok")) == canonical(parse("ok && ! ok || ok"))


def test_precedence_and_null_logic() -> None:
    assert ev("1 + 2 * 3") == 7
    assert ev("ok or ok and false", ok=True) is True
    assert ev("false and a > 1", a=None, ok=None) is False  # Kleene: false and NULL = false
    assert ev("true or a > 1", a=None) is True
    assert ev("a > 1", a=None) is None
    assert ev("isnull(a)", a=None) is True
    assert ev("coalesce(a, 5)", a=None) == 5


def test_money_style_decimal_rules() -> None:
    assert ev("x / 3", x=Decimal(1)) == Decimal("0.3333333333")
    assert ev("x / 3", x=Decimal(2)) == Decimal("0.6666666667")
    assert ev("x / 0", x=Decimal(2)) is None
    assert ev("round(x, 0)", x=Decimal("2.5")) == 3  # half away from zero, not banker's
    assert ev("round(x, 0)", x=Decimal("-2.5")) == -3
    assert ev("round(x, 2)", x=Decimal("1.005")) == Decimal("1.01")
    assert ev("a + x", a=1, x=Decimal("0.5")) == Decimal("1.5")


def test_integer_rules() -> None:
    assert ev("div(a, 2)", a=-7) == -3  # truncates toward zero
    assert ev("a % 3", a=-7) == -1  # sign of the dividend
    assert ev("a % 0", a=5) is None
    with pytest.raises(ExprOverflow):
        ev("a + 1", a=2**63 - 1)
    with pytest.raises(ExprOverflow):
        ev("a * 2", a=2**62)


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "1 +", "(1", "a ==", "x == null", "int", "1 / 2", "a + s", "ok + 1", "a and ok",
     "round(x, a)", "round(x, 11)", "unknown + 1", "foo(1)", "s < ok", "a in [x, 2]", "'\\q'", "1 2",
     "a % x", "div(x, 1)", "length(a)", "coalesce(a, s)", "9223372036854775808"],
)  # fmt: skip
def test_bad_input_is_a_positioned_expr_error(bad: str) -> None:
    with pytest.raises(ExprError) as err:
        check(parse(bad), S)
    assert isinstance(err.value.pos, int)


def test_unknown_field_lists_known_fields() -> None:
    with pytest.raises(ExprError, match="known fields: a, ok, s, x"):
        check(parse("zzz > 1"), S)


def test_limits() -> None:
    with pytest.raises(ExprError, match="longer"):
        parse("1" * (MAX_SOURCE_CHARS + 1))
    with pytest.raises(ExprError, match="longer"):
        parse("(" * 10000 + "1" + ")" * 10000)
    with pytest.raises(ExprError, match="nested too deeply"):
        parse("(" * 500 + "1" + ")" * 500)
    with pytest.raises(ExprError, match="nested too deeply"):
        parse("not " * (MAX_DEPTH + 2) + "true")
    with pytest.raises(ExprError, match="too large"):
        parse(" + ".join(["1"] * (MAX_NODES + 1)))


def test_sql_injection_is_inert() -> None:
    sql = to_sql(check(parse("s == \"x'); DROP TABLE t; --\""), S))
    assert "'x''); DROP TABLE t; --'" in sql  # quote doubled: stays inside one string literal
    with pytest.raises(ExprError):
        parse("s == 'a\x00b'")
    with pytest.raises(ExprError):
        check(parse('"; DROP TABLE t'), S)


def test_fuzzed_parser_only_ever_raises_expr_error() -> None:
    rng = random.Random(7)
    seeds = [gen(rng, rng.choice(["bool", "int", "decimal"]), 4) for _ in range(300)]
    alphabet = list("()[]'\"\\,+-*/%<>=!&|. 0123456789abxsdi") + ["and", "or", "not", "in", "\x00", "é"]
    for i in range(3000):
        text = list(rng.choice(seeds))
        for _ in range(rng.randrange(1, 6)):
            pos = rng.randrange(len(text) + 1)
            op = rng.randrange(3)
            if op == 0:
                text.insert(pos, rng.choice(alphabet))
            elif op == 1 and text:
                del text[min(pos, len(text) - 1)]
            else:
                text[min(pos, len(text) - 1) :] = list(rng.choice(seeds))[: rng.randrange(0, 30)]
        src = "".join(text)
        try:
            check(parse(src), SCHEMA)
        except ExprError:
            pass


def test_generated_expressions_all_typecheck_and_run() -> None:
    rng = random.Random(3)
    rows = make_rows(rng, 20)
    for _ in range(300):
        text = gen(rng, rng.choice(["bool", "int", "decimal"]), 4)
        fn = compile_python(check(parse(text), SCHEMA))
        for row in rows:
            try:
                fn(row)
            except ExprOverflow:
                pass


def test_no_eval_anywhere_in_the_engine() -> None:
    root = Path(__file__).resolve().parents[2] / "app" / "core" / "expr"
    pattern = re.compile(r"(?<!re\.)\b(eval|exec|compile|__import__|getattr|setattr)\s*\(")
    for path in root.glob("*.py"):
        code = "\n".join(
            line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#")
        )
        assert not pattern.search(code), f"{path.name} uses a dynamic-execution call"


def test_runtime_imports_only_the_standard_library() -> None:
    text = (Path(__file__).resolve().parents[2] / "app/core/expr/runtime.py").read_text(encoding="utf-8")
    imports = re.findall(r"^(?:from|import) (\S+)", text, re.M)
    assert set(imports) <= {"decimal", "fractions", "typing"}, imports
