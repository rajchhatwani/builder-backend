"""Op-log recording scope (B2-8 fix): requests that cannot change the spec take no project lock
and write no op; the lock is taken late, only for a commit that wrote spec tables; concurrent
writers keep a dense seq and an unbroken hash chain; rollback-then-commit records one op."""

import asyncio
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from httpx import AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models.entity import Entity
from app.models.spec_op import SpecOp
from app.services.ops import scope as ops_scope
from tests.api._auth_helpers import make_entity, make_project


@contextmanager
def _statements(engine: AsyncEngine) -> Iterator[list[str]]:
    seen: list[str] = []

    def spy(_conn: Any, _cur: Any, statement: str, *_a: Any) -> None:
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", spy)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", spy)


def _locks(seen: list[str]) -> list[str]:
    return [s for s in seen if "FOR NO KEY UPDATE" in s or "FOR UPDATE" in s]


def _op_writes(seen: list[str]) -> list[str]:
    return [s for s in seen if s.lstrip().upper().startswith("INSERT INTO SPEC_OPS")]


async def _ops(client: AsyncClient, pid: str) -> list[dict[str, Any]]:
    r = await client.get(f"/projects/{pid}/spec/ops?limit=200")
    assert r.status_code == 200, r.text
    return list(reversed(r.json()["items"]))


async def test_read_and_preview_requests_take_no_lock_and_write_no_op(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    pid = await make_project(client)
    await make_entity(client, pid, "Item")
    with _statements(engine) as seen:
        assert (await client.get(f"/projects/{pid}/spec")).status_code == 200
        assert (await client.post(f"/projects/{pid}/generate/preview")).status_code == 200
    assert _locks(seen) == []
    assert _op_writes(seen) == []
    assert len(await _ops(client, pid)) == 1


async def test_clean_or_non_spec_commit_in_a_scope_takes_no_lock(
    client: AsyncClient,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    pid = uuid.UUID(await make_project(client))
    async with session_factory() as db:
        await ops_scope.install(db, pid, ops_scope.SYSTEM)
        with _statements(engine) as seen:
            await db.commit()  # nothing written at all
        assert _locks(seen) == [] and _op_writes(seen) == []
    # the guard's own audit row rides on a mutating request without touching the spec
    with _statements(engine) as seen:
        r = await client.get(f"/projects/{pid}/spec/ops")
        assert r.status_code == 200
    assert _locks(seen) == []


async def test_a_spec_write_locks_once_at_commit_and_records_one_op(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    pid = await make_project(client)
    with _statements(engine) as seen:
        r = await client.post(f"/projects/{pid}/entities", json={"name": "Item"})
        assert r.status_code == 201
    assert len(_locks(seen)) == 1
    assert len(_op_writes(seen)) == 1
    # late: the lock comes after the entity insert, not before the handler's work
    first_insert = next(i for i, s in enumerate(seen) if "INSERT INTO entities" in s)
    lock_at = next(i for i, s in enumerate(seen) if "FOR NO KEY UPDATE" in s)
    assert lock_at > first_insert


async def test_concurrent_rest_writers_keep_dense_seq_and_an_unbroken_chain(
    client: AsyncClient,
) -> None:
    pid = await make_project(client)
    names = [f"Thing{c}" for c in "ABCDEFGH"]
    results = await asyncio.gather(
        *(client.post(f"/projects/{pid}/entities", json={"name": n}) for n in names)
    )
    assert [r.status_code for r in results] == [201] * len(names), [r.text for r in results]
    ops = await _ops(client, pid)
    assert [o["seq"] for o in ops] == list(range(1, len(names) + 1))
    assert ops[0]["spec_hash_before"] != ops[0]["spec_hash_after"]
    for prev, cur in zip(ops, ops[1:], strict=False):
        assert prev["spec_hash_after"] == cur["spec_hash_before"]
    spec = (await client.get(f"/projects/{pid}/spec")).json()
    assert sorted(e["name"] for e in spec["entities"]) == sorted(names)
    # the last op's hash is the hash of what is stored
    again = await client.post(
        f"/projects/{pid}/spec/ops", json={"op_type": "add_entity", "payload": {"entity": {"name": "Z"}}}
    )
    assert again.status_code == 201
    assert again.json()["seq"] == len(names) + 1


async def test_concurrent_rest_and_typed_writers_and_a_cold_cache(client: AsyncClient) -> None:
    pid = await make_project(client)
    ops_scope._LAST_SPEC.clear()  # noqa: SLF001
    jobs = [client.post(f"/projects/{pid}/entities", json={"name": f"R{i}"}) for i in range(4)]
    jobs += [
        client.post(
            f"/projects/{pid}/spec/ops",
            json={"op_type": "add_entity", "payload": {"entity": {"name": f"T{i}"}}},
        )
        for i in range(4)
    ]
    results = await asyncio.gather(*jobs)
    assert all(r.status_code == 201 for r in results), [r.text for r in results]
    ops = await _ops(client, pid)
    assert [o["seq"] for o in ops] == list(range(1, 9))
    for prev, cur in zip(ops, ops[1:], strict=False):
        assert prev["spec_hash_after"] == cur["spec_hash_before"]
    assert len((await client.get(f"/projects/{pid}/spec")).json()["entities"]) == 8


async def test_a_change_made_behind_the_cache_is_not_mistaken_for_the_cached_state(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = await make_project(client)
    await make_entity(client, pid, "A")  # cache now holds the spec after op 1
    async with session_factory() as db:  # an unlogged writer (no scope)
        db.add(Entity(project_id=uuid.UUID(pid), name="Sneaky", table_name="sneakies", plural_path="sneakies"))
        await db.commit()
    # the cache's hash still equals the log's last hash, so it is used: the sneaky row is
    # then part of this op's diff only if the cache is bypassed. Drop it as another process
    # would have (its own cache is empty) and the diff must be exactly the new entity.
    ops_scope._LAST_SPEC.clear()  # noqa: SLF001
    await make_entity(client, pid, "B")
    ops = await _ops(client, pid)
    assert [o["seq"] for o in ops] == [1, 2]
    spec = (await client.get(f"/projects/{pid}/spec")).json()
    assert {e["name"] for e in spec["entities"]} == {"A", "B", "Sneaky"}


async def test_rollback_then_commit_in_one_scope_records_exactly_one_op_under_the_lock(
    client: AsyncClient,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    pid = uuid.UUID(await make_project(client))
    async with session_factory() as db:
        await ops_scope.install(db, pid, ops_scope.SYSTEM)
        db.add(Entity(project_id=pid, name="Gone", table_name="gones", plural_path="gones"))
        await db.flush()
        await db.rollback()  # the first attempt is abandoned
        db.add(Entity(project_id=pid, name="Kept", table_name="kepts", plural_path="kepts"))
        with _statements(engine) as seen:
            await db.commit()
        assert len(_locks(seen)) == 1 and len(_op_writes(seen)) == 1
    async with session_factory() as db:
        names = list((await db.execute(select(Entity.name).where(Entity.project_id == pid))).scalars())
        count = (
            await db.execute(select(func.count()).select_from(SpecOp).where(SpecOp.project_id == pid))
        ).scalar_one()
    assert names == ["Kept"] and count == 1
    ops = await _ops(client, str(pid))
    assert [o["seq"] for o in ops] == [1] and ops[0]["op_type"] == "add_entity"


async def test_a_second_commit_after_the_first_records_again(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid = uuid.UUID(await make_project(client))
    async with session_factory() as db:
        await ops_scope.install(db, pid, ops_scope.SYSTEM)
        db.add(Entity(project_id=pid, name="One", table_name="ones", plural_path="ones"))
        await db.commit()
        db.add(Entity(project_id=pid, name="Two", table_name="twos", plural_path="twos"))
        await db.commit()
    ops = await _ops(client, str(pid))
    assert [o["seq"] for o in ops] == [1, 2]
    assert ops[0]["spec_hash_after"] == ops[1]["spec_hash_before"]
