"""Runtime configuration checks (generated): setting validation and gapless sequences."""

import uuid

import pytest

from app.core.errors import AppError
from app.db import session_factory
from app.runtime_config import sequences as _sequences
from app.runtime_config import settings as _settings


def test_every_setting_default_passes_its_own_validation() -> None:
    for key, definition in _settings.SETTINGS.items():
        assert _settings.check_value(key, definition["default"]) is not None


def test_setting_allow_backorders_refuses_a_non_boolean() -> None:
    with pytest.raises(AppError) as excinfo:
        _settings.check_value('allow_backorders', "yes")
    assert excinfo.value.status_code == 422


def test_setting_approval_threshold_refuses_a_non_integer() -> None:
    for bad in ("7", 1.5, True):
        with pytest.raises(AppError) as excinfo:
            _settings.check_value('approval_threshold', bad)
        assert excinfo.value.status_code == 422


def test_setting_invoice_footer_refuses_a_non_string() -> None:
    with pytest.raises(AppError) as excinfo:
        _settings.check_value('invoice_footer', 5)
    assert excinfo.value.status_code == 422


def test_setting_vat_rate_refuses_a_float_or_text() -> None:
    for bad in (1.5, "abc", True):
        with pytest.raises(AppError) as excinfo:
            _settings.check_value('vat_rate', bad)
        assert excinfo.value.status_code == 422


async def test_sequence_invoice_no_hands_out_consecutive_numbers_and_ignores_rollbacks() -> None:
    tenant = uuid.uuid4()
    kwargs = {"tenant_id": tenant}
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


async def test_sequence_order_no_hands_out_consecutive_numbers_and_ignores_rollbacks() -> None:
    kwargs = {}
    async with session_factory() as session:
        first = await _sequences.next_number(session, 'order_no', **kwargs)
        await session.commit()
    async with session_factory() as session:
        await _sequences.next_number(session, 'order_no', **kwargs)
        await session.rollback()  # this number was never used: it must come back
    async with session_factory() as session:
        second = await _sequences.next_number(session, 'order_no', **kwargs)
        await session.commit()
    assert first.endswith(str(1).zfill(4))
    assert second.endswith(str(2).zfill(4))
    assert first.startswith('ORD-') and second.startswith('ORD-')
