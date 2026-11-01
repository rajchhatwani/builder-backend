"""Runtime configuration checks (generated): setting validation and gapless sequences."""

import pytest

from app.core.errors import AppError
from app.db import session_factory
from app.runtime_config import sequences as _sequences
from app.runtime_config import settings as _settings


def test_every_setting_default_passes_its_own_validation() -> None:
    for key, definition in _settings.SETTINGS.items():
        assert _settings.check_value(key, definition["default"]) is not None


def test_setting_approval_threshold_refuses_a_non_integer() -> None:
    for bad in ("7", 1.5, True):
        with pytest.raises(AppError) as excinfo:
            _settings.check_value('approval_threshold', bad)
        assert excinfo.value.status_code == 422


def test_setting_payment_grace_days_refuses_a_non_integer() -> None:
    for bad in ("7", 1.5, True):
        with pytest.raises(AppError) as excinfo:
            _settings.check_value('payment_grace_days', bad)
        assert excinfo.value.status_code == 422


async def test_sequence_invoice_no_hands_out_consecutive_numbers_and_ignores_rollbacks() -> None:
    kwargs = {}
    async with session_factory() as session:
        first = await _sequences.next_number(session, 'invoice_no', **kwargs)
        await session.commit()
    async with session_factory() as session:
        await _sequences.next_number(session, 'invoice_no', **kwargs)
        await session.rollback()  # this number was never used: it must come back
    async with session_factory() as session:
        second = await _sequences.next_number(session, 'invoice_no', **kwargs)
        await session.commit()
    assert first.endswith(str(1).zfill(5))
    assert second.endswith(str(2).zfill(5))
    assert first.startswith('INV-') and second.startswith('INV-')
