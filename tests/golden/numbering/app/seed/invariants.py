"""Invariant checks on seeded rows (generated). Reads the database, not the generator's memory.

Checks, for every row the seed created: required columns set, enum values and lengths legal, numeric
bounds, uniqueness, every foreign key resolves, parent and child belong to the same tenant, tenant-scoped
rows have a seeded tenant, the state is a state of its machine and the state history is a legal chain
that ends in the current state. Returns a list of plain-text problems (empty = all good).
"""

import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Base
from app.seed.models import SeedRow

CHUNK = 5000
LIMIT = 200


def _chunks(items: list[Any]) -> list[list[Any]]:
    return [items[i : i + CHUNK] for i in range(0, len(items), CHUNK)]


async def check(
    session: AsyncSession,
    definitions: dict[str, Any],
    expected: dict[str, int] | None = None,
) -> list[str]:
    problems: list[str] = []
    seeded: dict[str, set[uuid.UUID]] = defaultdict(set)
    for table_name, record_id in (await session.execute(select(SeedRow.table_name, SeedRow.record_id))).all():
        seeded[table_name].add(record_id)
    tenant_table = definitions.get("tenant_table")
    tenant_ids = seeded.get(tenant_table, set()) if tenant_table else set()
    loaded: dict[str, dict[uuid.UUID, Any]] = {}
    for name in sorted(definitions["entities"]):
        d = definitions["entities"][name]
        ids = seeded.get(d["table"], set())
        if expected is not None and len(ids) != expected.get(name, 0):
            problems.append(f"{name}: {len(ids)} seeded rows tracked, the plan has {expected.get(name, 0)}")
        if not ids:
            continue
        table = Base.metadata.tables[d["table"]]
        stmt = select(table).where(
            table.c.id.in_(select(SeedRow.record_id).where(SeedRow.table_name == d["table"]))
        )
        rows = {r["id"]: r for r in (await session.execute(stmt)).mappings().all()}
        loaded[name] = rows
        if len(rows) != len(ids):
            problems.append(f"{name}: {len(ids) - len(rows)} seeded rows are missing from {d['table']}")
        _check_columns(name, d, rows, tenant_ids, problems)
        await _check_foreign_keys(session, definitions, name, d, rows, problems)
        if d.get("machine") is not None:
            await _check_states(session, name, d, rows, problems)
    if len(problems) > LIMIT:
        extra = len(problems) - LIMIT
        problems = [*problems[:LIMIT], f"... and {extra} more problems"]
    return problems


def _bad_value(f: dict[str, Any], value: Any) -> str | None:
    if f["type"] == "enum" and value not in (f["enum_values"] or []):
        return f"{value!r} is not one of {f['enum_values']}"
    if f["type"] in ("string", "text") and f["max_length"] is not None and len(value) > f["max_length"]:
        return f"longer than {f['max_length']} characters"
    if f["type"] in ("integer", "bigint", "float", "decimal"):
        number = Decimal(str(value))
        if f["min_value"] is not None and number < Decimal(str(f["min_value"])):
            return f"{value} is below {f['min_value']}"
        if f["max_value"] is not None and number > Decimal(str(f["max_value"])):
            return f"{value} is above {f['max_value']}"
    return None


def _check_columns(
    name: str, d: dict[str, Any], rows: dict[uuid.UUID, Any], tenant_ids: set[uuid.UUID], problems: list[str]
) -> None:
    unique_seen: dict[str, dict[Any, uuid.UUID]] = defaultdict(dict)
    for rid, row in rows.items():
        for fname, f in sorted(d["fields"].items()):
            value = row[fname]
            if value is None:
                if f["required"]:
                    problems.append(f"{name}[{rid}].{fname}: required but empty")
                continue
            why = _bad_value(f, value)
            if why:
                problems.append(f"{name}[{rid}].{fname}: {why}")
            if f["unique"]:
                if value in unique_seen[fname]:
                    problems.append(f"{name}[{rid}].{fname}: duplicate of {unique_seen[fname][value]}")
                unique_seen[fname][value] = rid
        if d["tenant_scoped"] and tenant_ids and row["tenant_id"] not in tenant_ids:
            problems.append(f"{name}[{rid}].tenant_id: {row['tenant_id']} is not a seeded tenant")


async def _check_foreign_keys(
    session: AsyncSession,
    definitions: dict[str, Any],
    name: str,
    d: dict[str, Any],
    rows: dict[uuid.UUID, Any],
    problems: list[str],
) -> None:
    for col, fk in sorted(d["fks"].items()):
        target = definitions["entities"][fk["target"]]
        parent = Base.metadata.tables[fk["table"]]
        wanted = sorted({r[col] for r in rows.values() if r[col] is not None}, key=str)
        parents: dict[uuid.UUID, Any] = {}
        for chunk in _chunks(wanted):
            columns = [parent.c.id] + ([parent.c.tenant_id] if target["tenant_scoped"] else [])
            for found in (await session.execute(select(*columns).where(parent.c.id.in_(chunk)))).all():
                parents[found[0]] = found[1] if target["tenant_scoped"] else None
        unique_seen: set[uuid.UUID] = set()
        for rid, row in rows.items():
            value = row[col]
            if value is None:
                if fk["required"]:
                    problems.append(f"{name}[{rid}].{col}: required but empty")
                continue
            if value not in parents:
                problems.append(f"{name}[{rid}].{col}: no {fk['target']} row {value}")
                continue
            if d["tenant_scoped"] and target["tenant_scoped"] and parents[value] != row["tenant_id"]:
                problems.append(f"{name}[{rid}].{col}: {fk['target']} {value} belongs to another tenant")
            if fk["unique"]:
                if value in unique_seen:
                    problems.append(f"{name}[{rid}].{col}: {value} is used by another row")
                unique_seen.add(value)


async def _check_states(
    session: AsyncSession, name: str, d: dict[str, Any], rows: dict[uuid.UUID, Any], problems: list[str]
) -> None:
    machine = d["machine"]
    log_table = Base.metadata.tables["state_transitions"]
    history: dict[uuid.UUID, list[Any]] = defaultdict(list)
    for chunk in _chunks(sorted(rows, key=str)):
        stmt = (
            select(log_table)
            .where(log_table.c.entity == name, log_table.c.record_id.in_(chunk))
            .order_by(log_table.c.created_at, log_table.c.id)
        )
        for entry in (await session.execute(stmt)).mappings().all():
            history[entry["record_id"]].append(entry)
    legal = {(t["name"], t["to"], bool(t["auto"])): set(t["from"]) for t in machine["transitions"]}
    for rid, row in rows.items():
        state = row[machine["field"]]
        if state not in machine["states"]:
            problems.append(f"{name}[{rid}].{machine['field']}: {state!r} is not a state")
        chain = history.get(rid, [])
        if not chain:
            problems.append(f"{name}[{rid}]: no state history")
            continue
        first = chain[0]
        if first["transition"] != "created" or first["from_state"] is not None or first["to_state"] != machine["initial"]:
            problems.append(f"{name}[{rid}]: the history does not start with 'created' in {machine['initial']!r}")
        for before, entry in zip(chain, chain[1:], strict=False):
            key = (entry["transition"], entry["to_state"], bool(entry["automatic"]))
            if entry["from_state"] != before["to_state"]:
                problems.append(f"{name}[{rid}]: history jumps from {before['to_state']!r} to {entry['from_state']!r}")
            elif key not in legal or entry["from_state"] not in legal[key]:
                problems.append(
                    f"{name}[{rid}]: transition {entry['transition']!r} {entry['from_state']!r} -> "
                    f"{entry['to_state']!r} is not allowed by the state machine"
                )
        if chain[-1]["to_state"] != state:
            problems.append(f"{name}[{rid}]: state is {state!r} but the history ends in {chain[-1]['to_state']!r}")
