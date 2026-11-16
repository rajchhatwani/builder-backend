"""Audit B1-059: generated auth test re-registers after account deletion (F-0881, F-0882)."""

from pathlib import Path

TPL = Path("app/core/generator/features/auth/templates/tests/test_auth.py.j2")


def _delete_test() -> str:
    src = TPL.read_text()
    return src.split("async def test_delete_account")[1].split("\nasync def ")[0]


def test_delete_account_reregisters_same_email_and_unique_values() -> None:
    body = _delete_test()
    # after the 401 checks the same email (and same unique custom values) must register again
    after = body.split("refresh.status_code == 401")[1]
    assert "registration_payload(EMAIL)" in after
    assert "/auth/register" in after
    assert "status_code == 201" in after
