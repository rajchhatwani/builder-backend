"""Change history checks (generated): the definitions and the value cap."""

from app.change_history import hooks
from app.change_history.definitions import HISTORY, MAX_VALUE_BYTES


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
