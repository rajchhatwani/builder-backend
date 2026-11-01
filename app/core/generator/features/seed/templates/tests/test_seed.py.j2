"""Seed data: the plan gives the same rows every time, the rows pass the invariants, seeding twice changes
nothing, reset removes only seeded rows, and the production guard refuses (generated)."""

import pytest
from sqlalchemy import func, select

from app.db import session_factory
from app.models import Base
from app.seed import engine, guard, runner
from app.seed.definitions import DEFINITIONS
from app.seed.models import SeedRow
from app.seed.plan import PROFILES

DEV_ENV = {"APP_ENV": "test"}


@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_a_profile_gives_the_same_rows_every_time(profile: str) -> None:
    first = engine.generate(DEFINITIONS, PROFILES[profile])
    second = engine.generate(DEFINITIONS, PROFILES[profile])
    assert first.digest() == second.digest()
    assert engine.canonical_dump(first) == engine.canonical_dump(second)


@pytest.mark.parametrize("profile", sorted(PROFILES))
async def test_seeding_twice_changes_nothing_and_the_invariants_hold(profile: str) -> None:
    first = await runner.seed(profile, env=DEV_ENV)
    assert first.status == "seeded"
    assert await runner.check() == []
    again = await runner.seed(profile, env=DEV_ENV)
    assert again.status == "already_seeded"
    assert again.digest == first.digest
    async with session_factory() as session:
        for name, count in first.counts.items():
            table = Base.metadata.tables[DEFINITIONS["entities"][name]["table"]]
            assert (await session.execute(select(func.count()).select_from(table))).scalar_one() == count


async def test_reset_removes_the_seeded_rows_and_nothing_else() -> None:
    profile = sorted(PROFILES)[0]
    await runner.seed(profile, env=DEV_ENV)
    report = await runner.reset(env=DEV_ENV)
    assert report.status == "reset"
    assert await runner.tracked() == 0
    async with session_factory() as session:
        for d in DEFINITIONS["entities"].values():
            table = Base.metadata.tables[d["table"]]
            assert (await session.execute(select(func.count()).select_from(table))).scalar_one() == 0


def test_the_guard_refuses_anything_but_a_development_environment() -> None:
    for bad in ({}, {"APP_ENV": "production"}, {"APP_ENV": "staging"}, {"APP_ENV": "development", "ENVIRONMENT": "prod"}):
        with pytest.raises(guard.SeedRefused):
            guard.require_safe_environment(bad)
    # one half of the override is not enough
    with pytest.raises(guard.SeedRefused):
        guard.require_safe_environment({"APP_ENV": "production"}, allow_production=True)
    with pytest.raises(guard.SeedRefused):
        guard.require_safe_environment({"APP_ENV": "production", "SEED_ALLOW_PRODUCTION": "yes"})
    guard.require_safe_environment({"APP_ENV": "development"})


async def test_seeding_in_production_writes_nothing() -> None:
    with pytest.raises(guard.SeedRefused):
        await runner.seed(sorted(PROFILES)[0], env={"APP_ENV": "production"})
    assert await runner.tracked() == 0
    assert not (await runner.check())
    assert SeedRow.__tablename__ == "seed_rows"
