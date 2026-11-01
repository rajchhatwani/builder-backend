"""Scenario tests for the generated `history_notes` project (notes and tickets). Copied into the project's
tests/ folder by tests/e2e/test_history_stack.py and run against a real Postgres.

Rules under test: every create, update and delete of an audited field leaves a row with the actor and the
old and new value; fields that are not audited never reach the table; an update that changes nothing logs
nothing; only the entity's view roles read the history; the purge command removes only expired rows; an
entity with a state machine AND history keeps both working.
"""

import asyncio
import datetime as dt
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from tests._auth_support import outbox, sign_in  # noqa: F401

from app.auth.models import AuthUser
from app.change_history import purge
from app.change_history.hooks import MARKER
from app.change_history.models import Change
from app.db import session_factory
from app.main import app
from app.state_machines.models import StateTransition

ROOT = Path(__file__).resolve().parent.parent
SECRET_TEXT = "the-private-note-must-never-be-logged"


@pytest.fixture
async def http(outbox) -> AsyncClient:  # noqa: ANN001, F811
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def people(http: AsyncClient) -> dict[str, dict[str, str]]:
    return {
        "agent": await sign_in(http, "agent@example.com", roles=["agent"], n=0),
        "auditor": await sign_in(http, "auditor@example.com", roles=["auditor"], n=1),
        "admin": await sign_in(http, "admin@example.com", roles=["admin"], n=2),
    }


async def user_id(email: str) -> uuid.UUID:
    async with session_factory() as session:
        return (await session.execute(select(AuthUser.id).where(AuthUser.email == email))).scalar_one()


async def rows(record_id: str | None = None) -> list[Change]:
    async with session_factory() as session:
        query = select(Change).order_by(Change.created_at, Change.field)
        if record_id is not None:
            query = query.where(Change.record_id == uuid.UUID(record_id))
        return list((await session.execute(query)).scalars())


async def make_note(http: AsyncClient, who: dict[str, str], **extra: object) -> dict:
    body = {"title": "First", "body": "hello", "payload": {"a": 1}, "private_note": SECRET_TEXT, **extra}
    response = await http.post("/notes", json=body, headers=who)
    assert response.status_code == 201, response.text
    return response.json()


def triples(changes: list[Change]) -> list[tuple[str, str, str | None, str | None]]:
    return sorted((c.op, c.field, c.old_value, c.new_value) for c in changes)


async def test_a_create_records_every_audited_field_with_the_actor(http, people) -> None:  # noqa: ANN001
    note = await make_note(http, people["agent"])
    found = await rows(note["id"])
    assert triples(found) == [
        ("create", "body", None, '"hello"'),
        ("create", "payload", None, '{"a": 1}'),
        ("create", "title", None, '"First"'),
    ]
    assert {c.actor_id for c in found} == {await user_id("agent@example.com")}
    assert {c.entity for c in found} == {"Note"}


async def test_an_update_records_only_what_changed(http, people) -> None:  # noqa: ANN001
    note = await make_note(http, people["agent"])
    done = await http.patch(f"/notes/{note['id']}", json={"title": "Second", "body": "hello"}, headers=people["admin"])
    assert done.status_code == 200, done.text
    updates = [c for c in await rows(note["id"]) if c.op == "update"]
    assert triples(updates) == [("update", "title", '"First"', '"Second"')]  # body was sent but is unchanged
    assert updates[0].actor_id == await user_id("admin@example.com")
    again = await http.patch(f"/notes/{note['id']}", json={"payload": {"a": 2, "b": [1, 2]}}, headers=people["agent"])
    assert again.status_code == 200
    last = [c for c in await rows(note["id"]) if c.field == "payload" and c.op == "update"]
    assert triples(last) == [("update", "payload", '{"a": 1}', '{"a": 2, "b": [1, 2]}')]


async def test_an_update_that_changes_nothing_logs_nothing(http, people) -> None:  # noqa: ANN001
    note = await make_note(http, people["agent"])
    before = len(await rows())
    same = await http.patch(
        f"/notes/{note['id']}", json={"title": "First", "payload": {"a": 1}}, headers=people["agent"]
    )
    assert same.status_code == 200
    assert (await http.patch(f"/notes/{note['id']}", json={}, headers=people["agent"])).status_code == 200
    replaced = await http.put(
        f"/notes/{note['id']}",
        json={"title": "First", "body": "hello", "payload": {"a": 1}, "private_note": SECRET_TEXT},
        headers=people["agent"],
    )
    assert replaced.status_code == 200, replaced.text
    assert len(await rows()) == before


async def test_fields_that_are_not_audited_never_reach_the_table(http, people) -> None:  # noqa: ANN001
    note = await make_note(http, people["agent"])
    changed = await http.patch(
        f"/notes/{note['id']}", json={"private_note": "another secret value"}, headers=people["agent"]
    )
    assert changed.status_code == 200
    await http.patch(f"/notes/{note['id']}", json={"title": "T2"}, headers=people["agent"])
    await http.delete(f"/notes/{note['id']}", headers=people["admin"])
    everything = await rows()
    assert everything and {c.field for c in everything} == {"title", "body", "payload"}
    for c in everything:
        assert SECRET_TEXT not in (c.old_value or "") + (c.new_value or "")
        assert "another secret" not in (c.old_value or "") + (c.new_value or "")


async def test_a_delete_records_the_old_values(http, people) -> None:  # noqa: ANN001
    note = await make_note(http, people["agent"])
    assert (await http.delete(f"/notes/{note['id']}", headers=people["admin"])).status_code == 204
    gone = [c for c in await rows(note["id"]) if c.op == "delete"]
    assert triples(gone) == [
        ("delete", "body", '"hello"', None),
        ("delete", "payload", '{"a": 1}', None),
        ("delete", "title", '"First"', None),
    ]
    assert {c.actor_id for c in gone} == {await user_id("admin@example.com")}


async def test_a_refused_write_leaves_no_history(http, people) -> None:  # noqa: ANN001
    note = await make_note(http, people["agent"])
    before = len(await rows())
    assert (await http.patch(f"/notes/{note['id']}", json={"title": "x" * 500}, headers=people["agent"])).status_code == 422
    assert (await http.patch(f"/notes/{note['id']}", json={"title": "ok"}, headers=people["auditor"])).status_code == 403
    assert len(await rows()) == before


async def test_big_values_are_cut_to_4_kb_with_a_marker(http, people) -> None:  # noqa: ANN001
    big = {"blob": "é" * 20000}
    note = await make_note(http, people["agent"], payload=big)
    stored = next(c for c in await rows(note["id"]) if c.field == "payload")
    assert stored.new_value is not None
    assert len(stored.new_value.encode("utf-8")) <= 4096 and stored.new_value.endswith(MARKER)
    await http.patch(f"/notes/{note['id']}", json={"payload": {"blob": "small"}}, headers=people["agent"])
    last = next(c for c in await rows(note["id"]) if c.op == "update")
    assert last.old_value is not None and last.old_value.endswith(MARKER) and last.new_value == '{"blob": "small"}'


async def test_only_the_view_roles_read_the_history(http, people) -> None:  # noqa: ANN001
    note = await make_note(http, people["agent"])
    await http.patch(f"/notes/{note['id']}", json={"title": "Second"}, headers=people["agent"])
    url = f"/notes/{note['id']}/history"
    assert (await http.get(url, headers=people["agent"])).status_code == 403  # may read the note, not its history
    assert (await http.get(url)).status_code == 401
    shown = await http.get(url, headers=people["auditor"])
    assert shown.status_code == 200
    body = shown.json()
    assert [(c["op"], c["field"]) for c in body if c["op"] == "update"] == [("update", "title")]
    assert body[-1]["old_value"] == '"First"' and body[-1]["new_value"] == '"Second"'
    assert body[-1]["actor_id"] == str(await user_id("agent@example.com"))
    assert (await http.get(url, headers=people["admin"])).status_code == 200
    assert (await http.get(f"/notes/{uuid.uuid4()}/history", headers=people["auditor"])).status_code == 404
    assert len((await http.get(url + "?limit=1", headers=people["admin"])).json()) == 1
    assert (await http.get(url + "?limit=0", headers=people["admin"])).status_code == 422


async def old_row(entity: str, days: int, field: str = "title") -> uuid.UUID:
    async with session_factory() as session:
        change = Change(
            entity=entity, record_id=uuid.uuid4(), field=field, new_value='"x"', op="create",
            created_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=days),
        )
        session.add(change)
        await session.commit()
        return change.id


async def test_purge_removes_only_rows_older_than_the_retention(http, people) -> None:  # noqa: ANN001
    note_old, note_edge = await old_row("Note", 91), await old_row("Note", 89)  # retention 90 days
    ticket_old, ticket_keep = await old_row("Ticket", 31, "subject"), await old_row("Ticket", 29, "subject")
    stranger = await old_row("Gone", 4000)  # no config any more: left alone
    fresh = await make_note(http, people["agent"])
    async with session_factory() as session:
        removed = await purge.purge(session)
    assert removed == {"Note": 1, "Ticket": 1}
    async with session_factory() as session:
        left = set((await session.execute(select(Change.id))).scalars())
    assert {note_old, ticket_old}.isdisjoint(left)
    assert {note_edge, ticket_keep, stranger} <= left
    assert len([c for c in await rows(fresh["id"])]) == 3
    # the command line entry point does the same (nothing left to remove now)
    done = subprocess.run(
        [sys.executable, "-m", "app.change_history.purge"], cwd=ROOT, env=dict(os.environ),
        capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 0, done.stderr
    assert "Note: 0 expired rows removed" in done.stdout and "Ticket: 0 expired rows removed" in done.stdout


async def test_an_entity_with_a_state_machine_and_history_keeps_both(http, people) -> None:  # noqa: ANN001
    made = await http.post("/tickets", json={"subject": "Printer", "assignee": "sam", "internal_memo": "m"}, headers=people["agent"])
    assert made.status_code == 201, made.text
    ticket = made.json()
    assert ticket["status"] == "open"  # the state machine's before_save hook ran
    ignored = await http.patch(f"/tickets/{ticket['id']}", json={"status": "closed"}, headers=people["admin"])
    assert ignored.status_code == 200 and ignored.json()["status"] == "open"  # the state is not writable
    moved = await http.post(f"/tickets/{ticket['id']}/transitions/start", headers=people["agent"])
    assert moved.status_code == 200 and moved.json()["status"] == "in_progress"
    await http.patch(f"/tickets/{ticket['id']}", json={"assignee": "kim", "internal_memo": "n"}, headers=people["agent"])
    found = await rows(ticket["id"])
    assert triples(found) == [
        ("create", "assignee", None, '"sam"'),
        ("create", "subject", None, '"Printer"'),
        ("update", "assignee", '"sam"', '"kim"'),
    ]
    async with session_factory() as session:
        states = (
            await session.execute(
                select(StateTransition.to_state).where(StateTransition.record_id == uuid.UUID(ticket["id"]))
                .order_by(StateTransition.created_at)
            )
        ).scalars().all()
    assert list(states) == ["open", "in_progress"]
    url = f"/tickets/{ticket['id']}/history"
    assert (await http.get(url, headers=people["auditor"])).status_code == 403  # tickets: admin only
    assert len((await http.get(url, headers=people["admin"])).json()) == 3
    assert json.loads((await http.get(url, headers=people["admin"])).text)[0]["field"] in {"assignee", "subject"}


async def test_parallel_updates_leave_a_gapless_old_to_new_chain(http, people) -> None:  # noqa: ANN001
    """15 simultaneous PATCHes: the hook locks the row before it snapshots the old values, so the
    updates run one after another. Every row's old_value is the previous row's new_value (the chain
    starts at the created title and ends at the stored one), whatever order the database picked."""
    note = await make_note(http, people["agent"])
    count = 15
    results = await asyncio.gather(
        *(http.patch(f"/notes/{note['id']}", json={"title": f"t{i}"}, headers=people["admin"]) for i in range(count))
    )
    assert [r.status_code for r in results] == [200] * count, [r.text for r in results]
    updates = [c for c in await rows(note["id"]) if c.op == "update" and c.field == "title"]
    assert len(updates) == count
    by_old = {c.old_value: c.new_value for c in updates}
    assert len(by_old) == count, "two updates replaced the same old value: the chain forked"
    chain, value = [], '"First"'
    while value in by_old:
        value = by_old[value]
        chain.append(value)
    assert len(chain) == count, chain  # every update is on the one path from the created title
    final = (await http.get(f"/notes/{note['id']}", headers=people["admin"])).json()["title"]
    assert chain[-1] == f'"{final}"'


async def test_history_paging_is_capped(http, people) -> None:  # noqa: ANN001
    note = await make_note(http, people["agent"])
    url = f"/notes/{note['id']}/history"
    assert (await http.get(url + "?offset=1000000", headers=people["admin"])).status_code == 200
    for bad in ("1000001", "99999999999999999999", "-1", "x"):
        refused = await http.get(url + f"?offset={bad}", headers=people["admin"])
        assert refused.status_code == 422, (bad, refused.status_code)
    for bad in ("1001", "99999999999999999999"):
        assert (await http.get(url + f"?limit={bad}", headers=people["admin"])).status_code == 422
