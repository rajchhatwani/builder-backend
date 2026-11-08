"""B1-3: the SQL emitter and the Python evaluator agree on random expressions and rows, on a real
Postgres (numeric, collation, bigint overflow are Postgres rules, not sqlite's).

Agreement rule: Python raises ExprOverflow  -> SQL may raise or return anything (SQL need not
evaluate every operand, so which side errors is undefined). Python returns a value -> SQL must
return the same value (decimals compared numerically, NULL == None) and must not raise.
"""

import asyncio
import random
from decimal import Decimal
from typing import Any

import asyncpg
import pytest
from testcontainers.community.postgres import PostgresContainer

from app.core.expr import SQL_SCHEMA, ExprOverflow, check, compile_python, parse, to_sql
from tests.expr_gen import SCHEMA, gen, make_rows

COLS = {"bool": "boolean", "int": "bigint", "decimal": "numeric", "string": "text"}
CASES = 700


@pytest.fixture(scope="module")
def pg_url() -> Any:
    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        yield url.replace("+psycopg2", "")


def same(a: object, b: object) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, Decimal) or isinstance(b, Decimal):
        return Decimal(a) == Decimal(b)  # type: ignore[arg-type]
    return a == b and type(a) is type(b)


async def _run(url: str) -> tuple[int, int, int]:
    rng = random.Random(20261031)
    rows = make_rows(rng)
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(SQL_SCHEMA)
        cols = ", ".join(f'"{n}" {COLS[t]}' for n, (t, _) in SCHEMA.items())
        await conn.execute(f"CREATE TABLE t (id int primary key, {cols})")
        names = list(SCHEMA)
        marks = ", ".join(f"${i + 2}" for i in range(len(names)))
        for i, row in enumerate(rows):
            await conn.execute(
                f"INSERT INTO t VALUES ($1, {marks})", i, *[row[n] for n in names]
            )
        compared = overflow_cases = 0
        for case in range(CASES):
            text = gen(rng, rng.choice(["bool", "int", "decimal", "bool"]), rng.randrange(1, 5))
            typed = check(parse(text), SCHEMA)
            fn = compile_python(typed)
            sql = to_sql(typed)
            expected: list[Any] = []
            for row in rows:
                try:
                    expected.append(fn(row))
                except ExprOverflow:
                    expected.append(ExprOverflow)
            try:
                got_rows = await conn.fetch(f"SELECT id, {sql} AS v FROM t ORDER BY id")
                got: list[Any] = [r["v"] for r in got_rows]
            except asyncpg.PostgresError:
                got = []
                for i in range(len(rows)):
                    try:
                        got.append((await conn.fetchrow(f"SELECT {sql} AS v FROM t WHERE id = {i}"))["v"])
                    except asyncpg.PostgresError:
                        got.append(ExprOverflow)
            for i, (e, g) in enumerate(zip(expected, got, strict=True)):
                if e is ExprOverflow:
                    overflow_cases += 1
                    continue
                assert g is not ExprOverflow, f"SQL raised but Python did not\n{text}\n{sql}\nrow={rows[i]}"
                assert same(e, g), f"MISMATCH case {case}\n{text}\n{sql}\nrow={rows[i]}\npython={e!r} sql={g!r}"
                compared += 1
        return CASES, compared, overflow_cases
    finally:
        await conn.close()


def test_sql_and_python_agree_on_random_expressions(pg_url: str) -> None:
    cases, compared, overflow = asyncio.run(_run(pg_url))
    assert cases >= 500 and compared > 10000
    print(f"parity: {cases} expressions, {compared} value comparisons, {overflow} overflow rows")
