"""Change history checks (generated): the definitions and the value cap."""

import datetime as _dt
import uuid as _uuid
from types import SimpleNamespace

import pytest

from app.change_history import hooks
from app.change_history import purge as _purge
from app.change_history.definitions import HISTORY, MAX_VALUE_BYTES
from app.crud.lifecycle import HookContext


def test_every_config_lists_fields_and_a_retention() -> None:
    for entity, config in HISTORY.items():
        assert config["fields"], entity
        assert 1 <= config["retention_days"] <= 3650, entity


def test_short_values_are_stored_as_json_text() -> None:
    assert hooks.stored(None) is None
    assert hooks.stored("a") == '"a"'
    assert hooks.stored({"k": [1, 2]}) == '{"k": [1, 2]}'


def test_long_values_are_cut_with_a_marker() -> None:
    cut = hooks.stored("é" * 10000)
    assert cut is not None
    assert len(cut.encode("utf-8")) <= MAX_VALUE_BYTES
    assert cut.endswith(hooks.MARKER)


def test_hooks_merge_per_stage_in_order() -> None:
    async def first(ctx: object) -> None: ...

    async def second(ctx: object) -> None: ...

    merged = hooks.merge_hooks({"after_save": (first,)}, {"after_save": (second,), "before_save": (second,)})
    assert merged == {"after_save": (first, second), "before_save": (second,)}


# --- recording, view roles and purge (no database: a stand-in session and row) ---------------------------------


class _Session:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.statements: list[object] = []
        self.committed = False

    def add(self, row: object) -> None:
        self.added.append(row)

    async def execute(self, stmt: object) -> SimpleNamespace:
        self.statements.append(stmt)
        return SimpleNamespace(rowcount=2)

    async def commit(self) -> None:
        self.committed = True


def _entity() -> tuple[str, tuple[str, ...]]:
    name = sorted(HISTORY)[0]
    return name, tuple(HISTORY[name]["fields"])


async def _run(monkeypatch: pytest.MonkeyPatch, op: str, before: dict[str, object], after: dict[str, object], actor: object) -> _Session:
    entity, _ = _entity()
    session = _Session()
    monkeypatch.setattr(hooks, "object_session", lambda _item: session)
    item = SimpleNamespace(id=_uuid.uuid4(), **after)
    ctx = HookContext(entity=entity, op=op, item=item, caller=actor)
    setattr(ctx, hooks._BEFORE, before)
    await hooks.hooks_for(entity)["after_save"][0](ctx)
    return session


async def test_create_records_each_listed_field_with_the_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    _, fields = _entity()
    actor = SimpleNamespace(id=_uuid.uuid4())
    session = await _run(monkeypatch, "create", {}, {name: "v" for name in fields}, actor)
    assert {row.field for row in session.added} == set(fields)  # type: ignore[attr-defined]
    assert all(row.op == "create" and row.actor_id == actor.id and row.old_value is None for row in session.added)  # type: ignore[attr-defined]


async def test_update_records_only_changed_listed_fields_and_never_others(monkeypatch: pytest.MonkeyPatch) -> None:
    _, fields = _entity()
    first = fields[0]
    before = {name: "a" for name in fields}
    after = {name: "a" for name in fields} | {first: "b", "secret_unlisted": "x"}
    session = await _run(monkeypatch, "update", before, after, None)
    assert [(row.field, row.old_value, row.new_value) for row in session.added] == [(first, '"a"', '"b"')]  # type: ignore[attr-defined]
    assert session.added[0].actor_id is None  # type: ignore[attr-defined]


async def test_update_without_a_change_records_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _, fields = _entity()
    same = {name: "a" for name in fields}
    assert (await _run(monkeypatch, "update", same, dict(same), None)).added == []


def test_every_entity_lists_view_roles() -> None:
    for entity, config in HISTORY.items():
        assert isinstance(config["view_roles"], list | tuple), entity


async def test_purge_cuts_at_each_entitys_retention() -> None:
    now = _dt.datetime(2030, 1, 1, tzinfo=_dt.UTC)
    session = _Session()
    removed = await _purge.purge(session, now)  # type: ignore[arg-type]
    assert session.committed and set(removed) == set(HISTORY)
    for stmt, entity in zip(session.statements, sorted(HISTORY), strict=True):
        params = stmt.compile().params  # type: ignore[attr-defined]
        cutoff = next(v for v in params.values() if isinstance(v, _dt.datetime))
        assert cutoff == now - _dt.timedelta(days=HISTORY[entity]["retention_days"]), entity
