"""Runtime configuration checks (generated): setting validation and gapless sequences."""

import pytest

from app.core.errors import AppError
from app.db import session_factory
from app.runtime_config import sequences as _sequences
from app.runtime_config import settings as _settings


def test_every_setting_default_passes_its_own_validation() -> None:
    for key, definition in _settings.SETTINGS.items():
        assert _settings.check_value(key, definition["default"]) is not None


def test_setting_carry_over_days_refuses_a_non_integer() -> None:
    for bad in ("7", 1.5, True):
        with pytest.raises(AppError) as excinfo:
            _settings.check_value('carry_over_days', bad)
        assert excinfo.value.status_code == 422


def test_setting_max_days_without_hr_refuses_a_non_integer() -> None:
    for bad in ("7", 1.5, True):
        with pytest.raises(AppError) as excinfo:
            _settings.check_value('max_days_without_hr', bad)
        assert excinfo.value.status_code == 422


async def test_sequence_request_no_hands_out_consecutive_numbers_and_ignores_rollbacks() -> None:
    kwargs = {}
    async with session_factory() as session:
        first = await _sequences.next_number(session, 'request_no', **kwargs)
        await session.commit()
    async with session_factory() as session:
        await _sequences.next_number(session, 'request_no', **kwargs)
        await session.rollback()  # this number was never used: it must come back
    async with session_factory() as session:
        second = await _sequences.next_number(session, 'request_no', **kwargs)
        await session.commit()
    assert first.endswith(str(1).zfill(4))
    assert second.endswith(str(2).zfill(4))
    assert first.startswith('LR-') and second.startswith('LR-')
