"""Random typed expression + row generator shared by the parity and fuzz tests (fixed seeds)."""

import random
from decimal import Decimal

SCHEMA = {
    "b1": ("bool", True), "b2": ("bool", True),
    "i1": ("int", True), "i2": ("int", True), "i3": ("int", True),
    "d1": ("decimal", True), "d2": ("decimal", True),
    "s1": ("string", True), "s2": ("string", True),
}  # fmt: skip

INTS = [0, 1, -1, 2, -2, 3, 7, -7, 10, 100, 2**62, 2**63 - 1, -(2**63), 2**31]
DECS = ["0", "0.5", "1.5", "2.5", "-2.5", "-0.5", "3.14159", "100", "0.0000000001", "123456.789", "-7.25", "1"]
STRS = ["", "a", "B", "abc", "é", "aa", "Z", "a'b", "10", "ab"]
INT_LITS = [0, 1, 2, 3, 5, 10, 100, 1000]
DEC_LITS = ["0.5", "1.5", "2.5", "0.25", "10.00", "3.333", "0.0000000001"]
STR_LITS = ["a", "ab", "B", "é", "", "x'y"]


def make_rows(rng: random.Random, n: int = 70) -> list[dict[str, object]]:
    def pick(options: list, null_rate: float = 0.2):  # type: ignore[no-untyped-def]
        return None if rng.random() < null_rate else rng.choice(options)

    rows: list[dict[str, object]] = []
    for _ in range(n):
        d1, d2 = pick(DECS), pick(DECS)
        rows.append(
            {
                "b1": pick([True, False]), "b2": pick([True, False]),
                "i1": pick(INTS), "i2": pick(INTS), "i3": pick(INT_LITS),
                "d1": None if d1 is None else Decimal(d1), "d2": None if d2 is None else Decimal(d2),
                "s1": pick(STRS), "s2": pick(STRS),
            }
        )  # fmt: skip
    return rows


def _q(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def gen(rng: random.Random, t: str, depth: int) -> str:
    leaf = depth <= 0 or rng.random() < 0.25
    if t == "bool":
        if leaf:
            return rng.choice(["b1", "b2", "true", "false"])
        c = rng.randrange(8)
        if c == 0:
            return f"({gen(rng, 'bool', depth - 1)} {rng.choice(['and', 'or', '&&', '||'])} {gen(rng, 'bool', depth - 1)})"
        if c == 1:
            return f"(not {gen(rng, 'bool', depth - 1)})"
        if c == 2:
            ty = rng.choice(["int", "decimal", "string", "bool"])
            op = rng.choice(["==", "!="] if ty == "bool" else ["==", "!=", "<", "<=", ">", ">="])
            return f"({gen(rng, ty, depth - 1)} {op} {gen(rng, ty, depth - 1)})"
        if c == 3:
            return f"isnull({gen(rng, rng.choice(['int', 'decimal', 'string', 'bool']), depth - 1)})"
        if c == 4:
            ty = rng.choice(["int", "string", "decimal"])
            lits = {"int": [str(rng.choice(INT_LITS)) for _ in range(3)],
                    "decimal": rng.choice([[rng.choice(DEC_LITS) for _ in range(2)], [str(rng.choice(INT_LITS)), rng.choice(DEC_LITS)]]),
                    "string": [_q(rng.choice(STR_LITS)) for _ in range(3)]}[ty]  # fmt: skip
            return f"({gen(rng, ty, depth - 1)} in [{', '.join(lits)}])"
        if c == 5:
            return f"({gen(rng, 'int', depth - 1)} {rng.choice(['<', '>=', '=='])} {gen(rng, 'decimal', depth - 1)})"
        if c == 6:
            return f"({gen(rng, 'decimal', depth - 1)} {rng.choice(['<', '>', '!='])} {gen(rng, 'int', depth - 1)})"
        return f"(length({gen(rng, 'string', depth - 1)}) > {rng.choice(INT_LITS)})"
    if t == "int":
        if leaf:
            return rng.choice(["i1", "i2", "i3", str(rng.choice(INT_LITS))])
        c = rng.randrange(7)
        if c <= 2:
            return f"({gen(rng, 'int', depth - 1)} {rng.choice(['+', '-', '*'])} {gen(rng, 'int', depth - 1)})"
        if c == 3:
            return f"div({gen(rng, 'int', depth - 1)}, {gen(rng, 'int', depth - 1)})"
        if c == 4:
            return f"({gen(rng, 'int', depth - 1)} % {gen(rng, 'int', depth - 1)})"
        if c == 5:
            return rng.choice([f"abs({gen(rng, 'int', depth - 1)})", f"(-{gen(rng, 'int', depth - 1)})",
                               f"length({gen(rng, 'string', depth - 1)})"])  # fmt: skip
        return f"coalesce({gen(rng, 'int', depth - 1)}, {gen(rng, 'int', depth - 1)})"
    if t == "decimal":
        if leaf:
            return rng.choice(["d1", "d2", rng.choice(DEC_LITS)])
        c = rng.randrange(8)
        if c <= 2:
            kinds = rng.choice([("decimal", "decimal"), ("int", "decimal"), ("decimal", "int")])
            return f"({gen(rng, kinds[0], depth - 1)} {rng.choice(['+', '-', '*'])} {gen(rng, kinds[1], depth - 1)})"
        if c == 3:
            kinds = rng.choice([("decimal", "decimal"), ("int", "decimal"), ("decimal", "int")])
            return f"({gen(rng, kinds[0], depth - 1)} / {gen(rng, kinds[1], depth - 1)})"
        if c == 4:
            return f"round({gen(rng, rng.choice(['decimal', 'int']), depth - 1)}, {rng.randrange(0, 4)})"
        if c == 5:
            return rng.choice([f"abs({gen(rng, 'decimal', depth - 1)})", f"(-{gen(rng, 'decimal', depth - 1)})"])
        if c == 6:
            return f"coalesce({gen(rng, 'decimal', depth - 1)}, {gen(rng, rng.choice(['int', 'decimal']), depth - 1)})"
        return f"({gen(rng, 'decimal', depth - 1)} * {rng.choice(DEC_LITS)})"
    if leaf:
        return rng.choice(["s1", "s2", _q(rng.choice(STR_LITS))])
    return f"coalesce({gen(rng, 'string', depth - 1)}, {gen(rng, 'string', depth - 1)})"
