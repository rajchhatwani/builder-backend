"""Op-log scope: a request whose session loaded spec rows before another writer committed must
record an op built from the fresh stored state (never undo the other writer's change), and a
write to the very same data fails closed with 409 and records nothing."""

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.entity import Entity
from app.models.spec_op import SpecOp
from app.services.ops import scope as ops_scope
from app.services.ops.canon import canonical_hash
from app.services.spec_service import SpecService
from tests.api._auth_helpers import make_entity, make_project


async def _ops(client: AsyncClient, pid: str) -> list[dict[str, Any]]:
    r = await client.get(f"/projects/{pid}/spec/ops?limit=200")
    assert r.status_code == 200, r.text
    return list(reversed(r.json()["items"]))


async def _stored_hash(factory: async_sessionmaker[AsyncSession], pid: uuid.UUID) -> str:
    async with factory() as db:
        return canonical_hash(await SpecService(db).assemble(pid))


async def _names(client: AsyncClient, pid: str) -> list[str]:
    spec = (await client.get(f"/projects/{pid}/spec")).json()
    return sorted(e["name"] for e in spec["entities"])


async def test_stale_identity_map_does_not_record_the_other_writers_change_as_undone(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid_s = await make_project(client)
    pid = uuid.UUID(pid_s)
    a_id = await make_entity(client, pid_s, "A")
    async with session_factory() as db:  # request A: loads the rows, then goes quiet
        await ops_scope.install(db, pid, ops_scope.SYSTEM)
        loaded = list((await db.execute(select(Entity).where(Entity.project_id == pid))).scalars())
        assert [e.name for e in loaded] == ["A"]
        # request B renames A and commits first
        r = await client.patch(f"/entities/{a_id}", json={"name": "Arenamed"})
        assert r.status_code == 200, r.text
        # request A now adds another entity and commits
        db.add(Entity(project_id=pid, name="Z", table_name="zs", plural_path="zs"))
        await db.commit()
    assert await _names(client, pid_s) == ["Arenamed", "Z"]
    ops = await _ops(client, pid_s)
    assert [o["seq"] for o in ops] == [1, 2, 3]
    assert ops[2]["op_type"] == "add_entity"
    for prev, cur in zip(ops, ops[1:], strict=False):
        assert prev["spec_hash_after"] == cur["spec_hash_before"]
    assert ops[-1]["spec_hash_after"] == await _stored_hash(session_factory, pid)
    # undoing request A's op restores B's state, not the original one
    assert (await client.post(f"/projects/{pid_s}/spec/undo")).status_code == 200
    assert await _names(client, pid_s) == ["Arenamed"]
    assert (await _ops(client, pid_s))[-1]["spec_hash_after"] == await _stored_hash(
        session_factory, pid
    )


async def test_same_row_conflict_fails_closed_with_409_and_records_nothing(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    pid_s = await make_project(client)
    pid = uuid.UUID(pid_s)
    a_id = await make_entity(client, pid_s, "A")
    before_ops = await _ops(client, pid_s)
    async with session_factory() as db:
        scope = await ops_scope.install(db, pid, ops_scope.SYSTEM)
        row = (await db.execute(select(Entity).where(Entity.project_id == pid))).scalar_one()
        r = await client.patch(f"/entities/{a_id}", json={"name": "Arenamed"})
        assert r.status_code == 200, r.text
        row.name = "Aother"  # a stale write to the same column of the same row
        try:
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            assert getattr(exc, "status_code", None) == 409
            assert getattr(exc, "code", None) == "spec_conflict"
        else:
            raise AssertionError("the lost update was not refused")
        scope.close()
    assert await _names(client, pid_s) == ["Arenamed"]
    ops = await _ops(client, pid_s)
    assert len(ops) == len(before_ops) + 1  # only B's rename was recorded
    assert ops[-1]["spec_hash_after"] == await _stored_hash(session_factory, pid)
    async with session_factory() as db:
        seqs = list(
            (await db.execute(select(SpecOp.seq).where(SpecOp.project_id == pid))).scalars()
        )
    assert sorted(seqs) == list(range(1, len(ops) + 1))
