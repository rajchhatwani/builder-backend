"""Guards that read settings (generated): fail closed when the settings were not loaded."""

from app.runtime_config.definitions import SETTINGS
from app.state_machines import engine
from app.state_machines.definitions import MACHINES


def test_a_guard_that_reads_settings_is_refused_when_they_were_not_loaded() -> None:
    checked = 0
    for entity, machine in MACHINES.items():
        for transition in machine["transitions"]:
            if engine._NEEDS.get((entity, transition["name"])):
                checked += 1
                # not even a row that would otherwise pass can get through without its settings
                assert engine.guard_holds(entity, transition, {}) is False
    assert checked > 0


def test_every_setting_a_guard_reads_exists() -> None:
    assert set(engine.USED_SETTINGS) <= set(SETTINGS)
