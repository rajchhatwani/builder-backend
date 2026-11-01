"""Deterministic seed engine (B1-9). Standard library only: this file is copied byte for byte into
generated projects as `app/seed/engine.py`, so it must never import anything from `app`.

Input is plain data: the project's DEFINITIONS (entities, columns, foreign keys, state machines) and one
seed-plan profile. Output is a list of rows in insertion order. Every random choice comes from
`random.Random` seeded with a hash of (profile seed, profile name, entity, column, tenant, index): the same
inputs always give the same rows, adding a column never reshuffles another one, and nothing reads the wall
clock, the environment or random uuids. Ids are uuid5 of (profile, table, tenant, index); timestamps start at the
profile's `as_of` date.

The plan only chooses among the generators below; there is no way to run code from it.
"""

import hashlib
import json
import random
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

NAMESPACE = uuid.UUID("5e0d5eed-0b19-4d5e-9a5e-5eed5eed5eed")
EMAIL_DOMAIN = "example.test"
STEP = timedelta(seconds=60)  # created_at distance between consecutive rows of one entity
LOG_STEP = timedelta(hours=1)  # distance between the states of one record's history
MAX_WORDS = 50

WORDS: tuple[str, ...] = (
    "amber", "anchor", "atlas", "beacon", "birch", "bridge", "cedar", "cobalt", "comet", "coral",
    "crest", "delta", "ember", "falcon", "fern", "fjord", "flint", "forest", "garnet", "glacier",
    "harbor", "hazel", "horizon", "indigo", "iris", "ivory", "jasper", "juniper", "kestrel", "lagoon",
    "lantern", "lotus", "maple", "meadow", "mist", "nectar", "nimbus", "oasis", "olive", "onyx",
    "opal", "orchid", "pebble", "pine", "prairie", "quartz", "raven", "reef", "ridge", "river",
    "sage", "sierra", "slate", "spruce", "summit", "tundra", "umber", "valley", "velvet", "willow",
    "zenith", "zephyr",
)
MAX_WORD_LENGTH = max(len(w) for w in WORDS)

GENERATOR_TYPES = (
    "constant",
    "one_of",
    "sequence",
    "int_range",
    "decimal_range",
    "date_range",
    "bool_ratio",
    "words",
    "email",
    "reference",
    "state",
)


class SeedError(Exception):
    """The plan cannot be turned into rows (validation normally catches this first)."""


@dataclass
class Row:
    table: str
    entity: str  # entity name; "" for a tenant
    id: uuid.UUID
    values: dict[str, Any]
    tenant: int | None = None  # index of the tenant the row belongs to
    log: list[dict[str, Any]] = field(default_factory=list)  # state history, oldest first


@dataclass
class SeedData:
    profile: str
    plan_hash: str
    tenants: list[Row]
    rows: list[Row]

    def all_rows(self) -> list[Row]:
        return [*self.tenants, *self.rows]

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.rows:
            out[r.entity] = out.get(r.entity, 0) + 1
        return out

    def digest(self) -> str:
        """SHA-256 of a canonical dump of every row and log entry (byte-stable)."""
        return hashlib.sha256(canonical_dump(self).encode("utf-8")).hexdigest()


def _plain(value: Any) -> Any:
    if isinstance(value, (datetime, date, Decimal, uuid.UUID)):
        return value.isoformat() if isinstance(value, (datetime, date)) else str(value)
    return value


def canonical_dump(data: SeedData) -> str:
    out = []
    for r in data.all_rows():
        out.append(
            {
                "table": r.table,
                "id": str(r.id),
                "values": {k: _plain(v) for k, v in sorted(r.values.items())},
                "log": [{k: _plain(v) for k, v in sorted(e.items())} for e in r.log],
            }
        )
    return json.dumps(out, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def plan_hash(definitions: dict[str, Any], profile: dict[str, Any]) -> str:
    raw = json.dumps(
        {"definitions": definitions, "profile": profile},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def rng_for(seed: int, profile: str, *parts: object) -> random.Random:
    key = "|".join([str(seed), profile, *[str(p) for p in parts]])
    return random.Random(int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:16], "big"))


def row_id(profile: str, table: str, tenant: int | None, index: int) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{profile}|{table}|{'-' if tenant is None else tenant}|{index}")


def base_time(as_of: str) -> datetime:
    y, m, d = (int(x) for x in as_of.split("-"))
    return datetime(y, m, d, tzinfo=UTC)


# --- value makers (one per generator type) ---------------------------------------------------


def decimal_of(value: str | int | float) -> Decimal:
    return Decimal(str(value))


def sequence_text(prefix: str, start: int, width: int, n: int) -> str:
    return f"{prefix}{start + n:0{width}d}"


def email_text(prefix: str, n: int) -> str:
    return f"{prefix}{n + 1}@{EMAIL_DOMAIN}"


def _coerce(ftype: str, value: Any) -> Any:
    """A constant or list item in the Python type of the column."""
    if ftype == "decimal":
        return decimal_of(value)
    if ftype == "float":
        return float(value)
    if ftype == "date":
        return date.fromisoformat(value)
    if ftype == "datetime":
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return value


def _make(
    gen: dict[str, Any], ftype: str, rng: random.Random, g: int
) -> Any:
    kind = gen["type"]
    if kind == "constant":
        return _coerce(ftype, gen["value"])
    if kind == "one_of":
        return _coerce(ftype, rng.choice(gen["values"]))
    if kind == "sequence":
        if ftype in ("integer", "bigint"):
            return int(gen.get("start") or 0) + g
        return sequence_text(gen.get("prefix") or "", int(gen.get("start") or 0), int(gen.get("width") or 0), g)
    if kind == "int_range":
        return rng.randint(int(gen["min"]), int(gen["max"]))
    if kind == "decimal_range":
        places = int(gen.get("places") or 0)
        scale = 10**places
        lo = int(decimal_of(gen["min"]) * scale)
        hi = int(decimal_of(gen["max"]) * scale)
        value = Decimal(rng.randint(lo, hi)).scaleb(-places)
        return float(value) if ftype == "float" else value
    if kind == "date_range":
        lo_d, hi_d = date.fromisoformat(str(gen["min"])), date.fromisoformat(str(gen["max"]))
        day = lo_d + timedelta(days=rng.randint(0, (hi_d - lo_d).days))
        if ftype == "datetime":
            return datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(
                seconds=rng.randrange(86400)
            )
        return day
    if kind == "bool_ratio":
        return rng.random() < float(gen["ratio"])
    if kind == "words":
        count = rng.randint(int(gen["min_words"]), int(gen["max_words"]))
        text = " ".join(rng.choice(WORDS) for _ in range(count))
        return text[0].upper() + text[1:]
    if kind == "email":
        return email_text(gen.get("prefix") or "user", g)
    raise SeedError(f"generator {kind!r} cannot make a {ftype} value")


# --- state machines --------------------------------------------------------------------------


def state_path(machine: dict[str, Any], target: str) -> list[dict[str, Any]] | None:
    """The shortest chain of transitions from the initial state to `target` (guards and roles are
    ignored: the seed writes states directly). Ties are broken by transition name."""
    initial = machine["initial"]
    if target == initial:
        return []
    transitions = sorted(machine["transitions"], key=lambda t: t["name"])
    seen = {initial}
    queue: deque[tuple[str, list[dict[str, Any]]]] = deque([(initial, [])])
    while queue:
        state, path = queue.popleft()
        for t in transitions:
            if state in t["from"] and t["to"] not in seen:
                chain = [*path, t]
                if t["to"] == target:
                    return chain
                seen.add(t["to"])
                queue.append((t["to"], chain))
    return None


def reachable_states(machine: dict[str, Any]) -> set[str]:
    return {s for s in machine["states"] if state_path(machine, s) is not None}


def _weighted(rng: random.Random, weights: dict[str, int]) -> str:
    total = sum(weights.values())
    pick = rng.randrange(total)
    for state in sorted(weights):
        pick -= weights[state]
        if pick < 0:
            return state
    raise SeedError("no state picked")  # unreachable: pick < total


# --- the planner -----------------------------------------------------------------------------


def seed_order(definitions: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    """Entities of the profile, every referenced entity before the entities that reference it."""
    plan = {e["entity"]: e for e in profile["entities"]}
    needs: dict[str, set[str]] = {name: set() for name in plan}
    for name, e in plan.items():
        for f in e["fields"]:
            if f["generator"]["type"] == "reference":
                needs[name].add(f["generator"]["entity"])
    order: list[str] = []
    done: set[str] = set()
    while len(order) < len(plan):
        ready = sorted(n for n in plan if n not in done and needs[n] <= done)
        if not ready:
            raise SeedError("the seed plan references entities in a loop")
        order.append(ready[0])
        done.add(ready[0])
    return order


def generate(definitions: dict[str, Any], profile: dict[str, Any]) -> SeedData:
    """The rows of one profile. Pure: the same arguments always give the same result."""
    name, seed = profile["name"], int(profile["seed"])
    base = base_time(profile["as_of"])
    tenant_table = definitions.get("tenant_table")
    tenant_count = int(profile.get("tenants") or 0)
    tenant_ids = [row_id(name, "tenant", None, t) for t in range(tenant_count)]
    tenants = [
        Row(
            table=tenant_table or "",
            entity="",
            id=tenant_ids[t],
            tenant=t,
            values={
                "name": f"{name.capitalize()} Tenant {t + 1:02d}",
                "created_at": base,
                "updated_at": base,
            },
        )
        for t in range(tenant_count if tenant_table else 0)
    ]
    rows: list[Row] = []
    by_entity: dict[str, dict[int | None, list[Row]]] = {}
    for ent in seed_order(definitions, profile):
        d = definitions["entities"][ent]
        plan = next(p for p in profile["entities"] if p["entity"] == ent)
        gens = {f["field"]: f["generator"] for f in plan["fields"]}
        scoped = bool(d["tenant_scoped"]) and tenant_count > 0
        groups: list[int | None] = list(range(tenant_count)) if scoped else [None]
        g = 0
        made: dict[int | None, list[Row]] = {}
        for t in groups:
            made[t] = []
            for i in range(int(plan["count"])):
                rid = row_id(name, d["table"], t, i)
                values: dict[str, Any] = {}
                for fname in sorted(d["fields"]):
                    gen = gens.get(fname)
                    if gen is None or gen["type"] == "state":
                        continue
                    rng = rng_for(seed, name, ent, fname, t, i)
                    values[fname] = _make(gen, d["fields"][fname]["type"], rng, g)
                for col in sorted(d["fks"]):
                    gen = gens.get(col)
                    if gen is None:
                        continue
                    target = gen["entity"]
                    pool_key = t if definitions["entities"][target]["tenant_scoped"] and tenant_count else None
                    pool = by_entity[target].get(pool_key, [])
                    if not pool:
                        values[col] = None
                        continue
                    rng = rng_for(seed, name, ent, col, t, i)
                    pick = pool[i % len(pool)] if (gen.get("pick") or "cycle") == "cycle" else pool[rng.randrange(len(pool))]
                    values[col] = pick.id
                if scoped and t is not None:
                    values["tenant_id"] = tenant_ids[t]
                created = base + STEP * g
                row = Row(table=d["table"], entity=ent, id=rid, values=values, tenant=t)
                machine = d.get("machine")
                last = created
                if machine is not None:
                    sgen = gens.get(machine["field"])
                    rng = rng_for(seed, name, ent, machine["field"], t, i)
                    target_state = _weighted(rng, sgen["weights"]) if sgen is not None else machine["initial"]
                    chain = state_path(machine, target_state)
                    if chain is None:
                        raise SeedError(f"{ent}: state {target_state!r} is not reachable")
                    row.log.append(
                        {"transition": "created", "from_state": None, "to_state": machine["initial"],
                         "automatic": False, "at": created}
                    )
                    previous = machine["initial"]
                    for k, t_ in enumerate(chain, start=1):
                        last = created + LOG_STEP * k
                        row.log.append(
                            {"transition": t_["name"], "from_state": previous, "to_state": t_["to"],
                             "automatic": bool(t_["auto"]), "at": last}
                        )
                        previous = t_["to"]
                    values[machine["field"]] = previous
                values["created_at"] = created
                values["updated_at"] = last
                rows.append(row)
                made[t].append(row)
                g += 1
        by_entity[ent] = made
    return SeedData(profile=name, plan_hash=plan_hash(definitions, profile), tenants=tenants, rows=rows)
