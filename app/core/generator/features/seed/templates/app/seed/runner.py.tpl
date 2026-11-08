"""Writes a seed profile to the database, removes it again, checks it (generated).

Everything goes through the generated tables and their constraints (not-null, unique, foreign keys), in
ONE transaction: a failure, a conflict or a failed invariant leaves the database as it was. The rows the
seed creates are listed in `seed_rows`; `reset` deletes exactly those rows.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_factory
from app.models import Base
from app.seed import engine, guard, invariants
from app.seed.definitions import DEFINITIONS
from app.seed.models import SeedRow
from app.seed.plan import PROFILES

CHUNK = 1000


class SeedError(Exception):
    """The request cannot be carried out; nothing was changed."""


class SeedConflict(SeedError):
    """The database already holds data that this run would clash with."""


class InvariantFailure(SeedError):
    """The seeded data broke an invariant; the run was rolled back."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__(f"{len(problems)} invariant problem(s):\n" + "\n".join(f"  - {p}" for p in problems))
        self.problems = problems


@dataclass
class Report:
    status: str  # seeded | already_seeded | reset
    profile: str = ""
    counts: dict[str, int] = field(default_factory=dict)
    digest: str = ""
    kept: list[str] = field(default_factory=list)


def _table(name: str) -> Any:
    return Base.metadata.tables[name]


async def _insert_rows(session: AsyncSession, table_name: str, rows: list[dict[str, Any]]) -> None:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(tuple(sorted(row)), []).append(row)
    for batch in groups.values():
        for i in range(0, len(batch), CHUNK):
            await session.execute(insert(_table(table_name)), batch[i : i + CHUNK])


async def _write(session: AsyncSession, data: engine.SeedData) -> None:
    pending: list[dict[str, Any]] = []
    table = ""

    async def flush() -> None:
        nonlocal pending
        if pending:
            await _insert_rows(session, table, pending)
        pending = []

    for row in data.all_rows():
        if row.table != table:
            await flush()
            table = row.table
        pending.append({"id": row.id, **row.values})
    await flush()
    logs = [
        {
            "id": uuid.uuid5(engine.NAMESPACE, f"{row.id}|log|{k}"),
            "entity": row.entity,
            "record_id": row.id,
            "transition": e["transition"],
            "from_state": e["from_state"],
            "to_state": e["to_state"],
            "actor_id": None,
            "automatic": e["automatic"],
            "created_at": e["at"],
        }
        for row in data.rows
        for k, e in enumerate(row.log)
    ]
    await _insert_rows(session, "state_transitions", logs)
    await _insert_rows(
        session,
        "seed_rows",
        [
            {"table_name": r.table, "record_id": r.id, "profile": data.profile, "plan_hash": data.plan_hash}
            for r in data.all_rows()
        ],
    )


async def seed(
    profile: str,
    *,
    allow_production: bool = False,
    env: Mapping[str, str] | None = None,
) -> Report:
    """Create the rows of `profile`. Running it again with the same plan changes nothing; a different
    plan or profile already in the database is refused (run `reset` first)."""
    guard.require_safe_environment(env, allow_production=allow_production)
    if profile not in PROFILES:
        raise SeedError(f"no seed profile named {profile!r}; profiles: {', '.join(sorted(PROFILES))}")
    data = engine.generate(DEFINITIONS, PROFILES[profile])
    expected = {(r.table, r.id) for r in data.all_rows()}
    async with session_factory() as session:
        try:
            async with session.begin():
                held = (
                    await session.execute(
                        select(SeedRow.table_name, SeedRow.record_id, SeedRow.profile, SeedRow.plan_hash)
                    )
                ).all()
                if held:
                    others = sorted({h[2] for h in held} - {profile})
                    if others:
                        raise SeedConflict(
                            f"the database holds seed data of profile {', '.join(others)}: "
                            "run with --reset first"
                        )
                    same = {(h[0], h[1]) for h in held} == expected and {h[3] for h in held} == {data.plan_hash}
                    if not same:
                        raise SeedConflict(
                            f"profile {profile!r} was seeded from a different plan: run with --reset to replace it"
                        )
                    problems = await invariants.check(session, DEFINITIONS, data.counts())
                    if problems:
                        raise InvariantFailure(problems)
                    return Report("already_seeded", profile, data.counts(), data.digest())
                await _write(session, data)
                await session.flush()
                problems = await invariants.check(session, DEFINITIONS, data.counts())
                if problems:
                    raise InvariantFailure(problems)
        except IntegrityError as exc:
            raise SeedConflict(
                "the database refused a seed row (existing data clashes with the plan, for example a "
                f"unique value that is already taken): {exc.orig}"
            ) from exc
    return Report("seeded", profile, data.counts(), data.digest())


async def reset(
    *, allow_production: bool = False, env: Mapping[str, str] | None = None
) -> Report:
    """Delete the rows the seed created, and only those. Refuses (changing nothing) when data that the
    seed did not create still points at a seeded row; a seeded tenant that people have joined is kept."""
    guard.require_safe_environment(env, allow_production=allow_production)
    tenant_table = DEFINITIONS.get("tenant_table")
    machine_entities = {
        d["table"]: name for name, d in DEFINITIONS["entities"].items() if d.get("machine") is not None
    }
    counts: dict[str, int] = {}
    kept: list[str] = []
    async with session_factory() as session, session.begin():
        seeded_tables = {t for (t,) in (await session.execute(select(SeedRow.table_name).distinct())).all()}

        def seeded_ids(name: str) -> Any:
            return select(SeedRow.record_id).where(SeedRow.table_name == name)

        kept_ids: set[uuid.UUID] = set()
        blockers: list[str] = []
        for parent in sorted(seeded_tables):
            for child in Base.metadata.sorted_tables:
                for fk in child.foreign_keys:
                    if fk.column.table.name != parent:
                        continue
                    where = fk.parent.in_(seeded_ids(parent))
                    if child.name in seeded_tables and "id" in child.c:
                        where = where & child.c.id.not_in(seeded_ids(child.name))
                    found = (await session.execute(select(fk.parent).where(where))).scalars().all()
                    if not found:
                        continue
                    if parent == tenant_table:
                        kept_ids.update(found)
                    else:
                        blockers.append(f"{len(found)} row(s) of {child.name}.{fk.parent.name} -> {parent}")
        if blockers:
            raise SeedConflict(
                "refusing to reset: rows that the seed did not create still point at seeded rows: "
                + "; ".join(blockers)
                + ". Delete or move them first."
            )
        for table in reversed(Base.metadata.sorted_tables):
            if table.name not in seeded_tables:
                continue
            scope = table.c.id.in_(seeded_ids(table.name))
            tracked_scope = SeedRow.table_name == table.name
            if table.name == tenant_table and kept_ids:
                scope = scope & table.c.id.not_in(kept_ids)
                tracked_scope = tracked_scope & SeedRow.record_id.not_in(kept_ids)
                kept = sorted(str(k) for k in kept_ids)
            if table.name in machine_entities:
                log = _table("state_transitions")
                doomed = select(table.c.id).where(scope)
                await session.execute(
                    delete(log).where(
                        log.c.entity == machine_entities[table.name], log.c.record_id.in_(doomed)
                    )
                )
            result = await session.execute(delete(table).where(scope))
            counts[table.name] = int(result.rowcount or 0)  # type: ignore[attr-defined]
            await session.execute(delete(SeedRow).where(tracked_scope))
    return Report("reset", counts=counts, kept=kept)


async def check() -> list[str]:
    """The invariant problems of the seed rows now in the database (empty = all good)."""
    async with session_factory() as session:
        return await invariants.check(session, DEFINITIONS)


async def tracked() -> int:
    async with session_factory() as session:
        return int((await session.execute(select(func.count()).select_from(SeedRow))).scalar_one())
