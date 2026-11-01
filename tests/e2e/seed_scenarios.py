"""Scenario tests for the generated `seed_demo` project (customers and invoices, tenants, an invoice state
machine, two seed profiles). Copied into the project's tests/ folder by tests/e2e/test_seed_stack.py and
run against a real Postgres.

Rules under test: seeding twice (with --reset between) gives byte-identical data; seeding again without
--reset changes nothing; the invariants hold and fail loudly when the data is damaged; the production guard
refuses unless the flag AND the environment variable are both set; --reset removes only seeded rows and
refuses (changing nothing) when other data points at them; seeded invoices have legal states and history.
"""

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, insert, select, text, update

from app.db import session_factory
from app.models import Base
from app.seed.definitions import DEFINITIONS
from app.seed.plan import PROFILES

ROOT = Path(__file__).resolve().parent.parent
TABLES = ("auth_tenants", "customers", "invoices", "state_transitions", "seed_rows")


def cli(*args: str, env: dict[str, str] | None = None, **extra: str) -> subprocess.CompletedProcess[str]:
    full = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "APP_ENV", "ENVIRONMENT", "SEED_ALLOW_PRODUCTION")}
    full["APP_ENV"] = "development"
    full.update(extra)
    if env is not None:
        full = {**{k: v for k, v in full.items() if k in ("DATABASE_URL", "PATH", "HOME")}, **env}
    return subprocess.run(
        [sys.executable, "-m", "app.seed", *args], cwd=ROOT, env=full, capture_output=True, text=True, timeout=300
    )


async def dump() -> str:
    """A canonical hash of every row of every seed-touched table."""
    out: dict[str, list[dict[str, Any]]] = {}
    async with session_factory() as session:
        for name in TABLES:
            table = Base.metadata.tables[name]
            rows = (await session.execute(select(table))).mappings().all()
            out[name] = sorted(({k: str(v) for k, v in r.items()} for r in rows), key=lambda r: json.dumps(r, sort_keys=True))
    return hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest()


async def count(table: str) -> int:
    async with session_factory() as session:
        return (await session.execute(select(func.count()).select_from(Base.metadata.tables[table]))).scalar_one()


def digest_of(result: subprocess.CompletedProcess[str]) -> str:
    return next(line.split(": ", 1)[1] for line in result.stdout.splitlines() if line.startswith("digest:"))


async def test_seeding_twice_with_a_reset_gives_identical_data() -> None:
    first = cli("--profile", "demo")
    assert first.returncode == 0, first.stderr + first.stdout
    snapshot = await dump()
    assert await count("customers") == 10 and await count("invoices") == 16 and await count("auth_tenants") == 2
    second = cli("--profile", "demo", "--reset")
    assert second.returncode == 0, second.stderr + second.stdout
    assert digest_of(first) == digest_of(second)
    assert await dump() == snapshot  # same ids, values, timestamps and history, byte for byte


async def test_seeding_again_without_reset_changes_nothing() -> None:
    assert cli("--profile", "demo").returncode == 0
    snapshot = await dump()
    again = cli("--profile", "demo")
    assert again.returncode == 0, again.stderr
    assert "already_seeded" in again.stdout
    assert await dump() == snapshot
    assert await count("invoices") == 16  # no duplicates


async def test_another_profile_is_refused_until_reset() -> None:
    assert cli("--profile", "demo").returncode == 0
    snapshot = await dump()
    refused = cli("--profile", "dev")
    assert refused.returncode == 4 and "run with --reset" in refused.stderr
    assert await dump() == snapshot
    swapped = cli("--profile", "dev", "--reset")
    assert swapped.returncode == 0, swapped.stderr
    assert await count("customers") == 120 and await count("invoices") == 360


async def test_invariants_hold_and_invoices_have_legal_states_and_history() -> None:
    assert cli("--profile", "dev").returncode == 0
    checked = cli("--check")
    assert checked.returncode == 0, checked.stderr
    machine = DEFINITIONS["entities"]["Invoice"]["machine"]
    invoices, logs = Base.metadata.tables["invoices"], Base.metadata.tables["state_transitions"]
    async with session_factory() as session:
        states = {r[0] for r in (await session.execute(select(invoices.c.status).distinct())).all()}
        assert states <= set(machine["states"]) and len(states) >= 4
        per_invoice = (await session.execute(select(logs.c.record_id, func.count()).group_by(logs.c.record_id))).all()
        assert len(per_invoice) == 360 and all(n >= 1 for _, n in per_invoice)
        last = {
            r[0]: r[1]
            for r in (
                await session.execute(
                    select(logs.c.record_id, logs.c.to_state).order_by(logs.c.created_at.desc())
                )
            ).all()[::-1]
        }
        current = {r[0]: r[1] for r in (await session.execute(select(invoices.c.id, invoices.c.status))).all()}
        assert last == current


async def test_every_seeded_row_carries_its_tenant_and_tenants_never_mix() -> None:
    assert cli("--profile", "demo").returncode == 0
    customers, invoices = Base.metadata.tables["customers"], Base.metadata.tables["invoices"]
    async with session_factory() as session:
        crossing = (
            await session.execute(
                select(func.count())
                .select_from(invoices.join(customers, invoices.c.customer_id == customers.c.id))
                .where(invoices.c.tenant_id != customers.c.tenant_id)
            )
        ).scalar_one()
        assert crossing == 0
        assert (await session.execute(select(func.count()).where(invoices.c.tenant_id.is_(None)))).scalar_one() == 0


async def test_damaged_data_fails_the_check_loudly() -> None:
    assert cli("--profile", "demo").returncode == 0
    invoices, customers, logs = (Base.metadata.tables[n] for n in ("invoices", "customers", "state_transitions"))
    async with session_factory() as session:
        invoice_id = (await session.execute(select(invoices.c.id).limit(1))).scalar_one()
        await session.execute(update(invoices).where(invoices.c.id == invoice_id).values(status="bogus"))
        await session.commit()
    bad_state = cli("--check")
    assert bad_state.returncode == 5 and "is not a state" in bad_state.stderr and str(invoice_id) in bad_state.stderr
    async with session_factory() as session:
        await session.execute(delete_log(logs, invoice_id))
        await session.commit()
    no_history = cli("--check")
    assert no_history.returncode == 5 and "no state history" in no_history.stderr
    # a customer moved into another tenant: its invoices now point across tenants
    async with session_factory() as session:
        tenants = [r[0] for r in (await session.execute(select(Base.metadata.tables["auth_tenants"].c.id))).all()]
        row = (await session.execute(select(customers.c.id, customers.c.tenant_id).limit(1))).one()
        other = next(t for t in tenants if t != row[1])
        await session.execute(update(customers).where(customers.c.id == row[0]).values(tenant_id=other))
        await session.commit()
    assert "belongs to another tenant" in cli("--check").stderr


async def test_a_state_that_the_history_does_not_explain_fails_the_check() -> None:
    assert cli("--profile", "demo").returncode == 0
    invoices, logs = Base.metadata.tables["invoices"], Base.metadata.tables["state_transitions"]
    async with session_factory() as session:
        invoice_id, status = (await session.execute(select(invoices.c.id, invoices.c.status).limit(1))).one()
        other = "rejected" if status != "rejected" else "draft"
        await session.execute(update(invoices).where(invoices.c.id == invoice_id).values(status=other))
        await session.commit()
    found = cli("--check")
    assert found.returncode == 5 and "the history ends in" in found.stderr and str(invoice_id) in found.stderr
    async with session_factory() as session:  # put it back, then add a move the machine does not allow
        await session.execute(update(invoices).where(invoices.c.id == invoice_id).values(status=status))
        last = (
            await session.execute(
                select(logs.c.to_state, logs.c.created_at).where(logs.c.record_id == invoice_id).order_by(logs.c.created_at.desc()).limit(1)
            )
        ).one()
        await session.execute(
            insert(logs).values(
                id=uuid.uuid4(), entity="Invoice", record_id=invoice_id, transition="pay",
                from_state="draft", to_state=last[0], actor_id=None, automatic=False,
                created_at=last[1] + dt.timedelta(hours=5),
            )
        )
        await session.commit()
    illegal = cli("--check")
    assert illegal.returncode == 5 and ("jumps from" in illegal.stderr or "is not allowed" in illegal.stderr)


def delete_log(logs: Any, record_id: uuid.UUID) -> Any:
    return logs.delete().where(logs.c.record_id == record_id)


async def test_the_production_guard_refuses_and_needs_both_halves_of_the_override() -> None:
    for env in (
        {"APP_ENV": "production"},
        {"APP_ENV": "prod"},
        {"APP_ENV": "staging"},
        {"APP_ENV": "development", "ENVIRONMENT": "production"},
        {"ENVIRONMENT": ""},  # APP_ENV missing: unknown environment
    ):
        refused = cli("--profile", "demo", env={"DATABASE_URL": os.environ["DATABASE_URL"], **env})
        assert refused.returncode == 3 and "REFUSED" in refused.stderr, (env, refused.stderr)
        assert await count("customers") == 0 and await count("seed_rows") == 0
    flag_only = cli("--profile", "demo", "--allow-production", APP_ENV="production")
    assert flag_only.returncode == 3 and await count("customers") == 0
    var_only = cli("--profile", "demo", APP_ENV="production", SEED_ALLOW_PRODUCTION="yes")
    assert var_only.returncode == 3 and await count("customers") == 0
    wrong_value = cli("--profile", "demo", "--allow-production", APP_ENV="production", SEED_ALLOW_PRODUCTION="1")
    assert wrong_value.returncode == 3 and await count("customers") == 0
    reset_refused = cli("--reset-only", APP_ENV="production")
    assert reset_refused.returncode == 3
    both = cli("--profile", "demo", "--allow-production", APP_ENV="production", SEED_ALLOW_PRODUCTION="yes")
    assert both.returncode == 0, both.stderr
    assert await count("customers") == 10
    # a read-only check is allowed anywhere
    assert cli("--check", APP_ENV="production").returncode == 0


async def test_reset_removes_only_seeded_rows() -> None:
    assert cli("--profile", "demo").returncode == 0
    tenants, customers = Base.metadata.tables["auth_tenants"], Base.metadata.tables["customers"]
    mine_tenant, mine_customer = uuid.uuid4(), uuid.uuid4()
    async with session_factory() as session:
        await session.execute(insert(tenants).values(id=mine_tenant, name="Real Tenant"))
        await session.execute(
            insert(customers).values(id=mine_customer, name="Real Customer", email="real@acme.test", tenant_id=mine_tenant)
        )
        await session.commit()
    result = cli("--reset-only")
    assert result.returncode == 0, result.stderr
    assert await count("invoices") == 0 and await count("seed_rows") == 0
    assert await count("customers") == 1 and await count("auth_tenants") == 1
    async with session_factory() as session:
        assert (await session.execute(select(customers.c.id))).scalars().all() == [mine_customer]
        assert (await session.execute(select(tenants.c.id))).scalars().all() == [mine_tenant]


async def test_reset_keeps_a_seeded_tenant_that_real_data_uses() -> None:
    assert cli("--profile", "demo").returncode == 0
    tenants, customers = Base.metadata.tables["auth_tenants"], Base.metadata.tables["customers"]
    async with session_factory() as session:
        seeded_tenant = (await session.execute(select(tenants.c.id).order_by(tenants.c.name).limit(1))).scalar_one()
        await session.execute(
            insert(customers).values(id=uuid.uuid4(), name="Real", email="real@acme.test", tenant_id=seeded_tenant)
        )
        await session.commit()
    result = cli("--reset-only")
    assert result.returncode == 0, result.stderr
    assert "kept 1 seeded tenant" in result.stdout
    assert await count("customers") == 1 and await count("auth_tenants") == 1


async def test_reset_refuses_when_real_data_points_at_a_seeded_row() -> None:
    assert cli("--profile", "demo").returncode == 0
    invoices, customers = Base.metadata.tables["invoices"], Base.metadata.tables["customers"]
    async with session_factory() as session:
        parent = (await session.execute(select(customers.c.id, customers.c.tenant_id).limit(1))).one()
        await session.execute(
            insert(invoices).values(
                id=uuid.uuid4(), invoice_no="REAL-1", amount=5, issued_on=dt.date(2026, 1, 1),
                status="draft", customer_id=parent[0], tenant_id=parent[1],
            )
        )
        await session.commit()
    snapshot = await dump()
    refused = cli("--reset-only")
    assert refused.returncode == 4 and "refusing to reset" in refused.stderr
    assert await dump() == snapshot  # nothing was deleted


async def test_seeding_into_clashing_data_rolls_back_completely() -> None:
    tenants, customers = Base.metadata.tables["auth_tenants"], Base.metadata.tables["customers"]
    tenant = uuid.uuid4()
    async with session_factory() as session:
        await session.execute(insert(tenants).values(id=tenant, name="Real"))
        await session.execute(
            insert(customers).values(id=uuid.uuid4(), name="Real", email="customer1@example.test", tenant_id=tenant)
        )
        await session.commit()
    refused = cli("--profile", "demo")
    assert refused.returncode == 4 and "refused a seed row" in refused.stderr
    assert await count("seed_rows") == 0 and await count("invoices") == 0 and await count("customers") == 1
    assert await count("auth_tenants") == 1


async def test_the_listing_and_usage_errors() -> None:
    listed = cli("--list")
    assert listed.stdout.split() == sorted(PROFILES)
    assert cli().returncode == 2
    assert cli("--profile", "nope").returncode == 2
    assert cli("--reset-only", "--profile", "demo").returncode == 2
    await _no_tables_changed()


async def _no_tables_changed() -> None:
    async with session_factory() as session:
        assert (await session.execute(text("SELECT count(*) FROM seed_rows"))).scalar_one() == 0
