"""Review F-009: the audit `detail` sanitizer is the control behind "never log secrets"."""

import pytest

from app.services import audit_service
from app.services.audit_service import _clean_detail


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "new_password",
        "PASSWORD",
        "token",
        "api_token",
        "refresh_token_hash",
        "bearer_token",
        "secret",
        "client_secret",
        "totp_secret",
        "Authorization",
        "authorization_header",
        "cookie",
        "set-cookie",
        "otp",
        "otp_code",
    ],
)
def test_secret_looking_keys_are_dropped(key: str) -> None:
    assert _clean_detail({key: "hunter2", "plan": "team"}) == {"plan": "team"}


def test_only_secret_keys_leave_nothing() -> None:
    assert _clean_detail({"password": "x", "token": "y"}) is None


@pytest.mark.parametrize("empty", [None, {}])
def test_empty_detail_is_none(empty: dict[str, object] | None) -> None:
    assert _clean_detail(empty) is None


def test_every_forbidden_fragment_is_still_listed() -> None:
    # Guards the list itself: an emptied tuple would silently let everything through.
    assert set(audit_service._FORBIDDEN_DETAIL_KEYS) >= {  # noqa: SLF001
        "password",
        "token",
        "secret",
        "authorization",
        "cookie",
        "otp",
    }


def test_values_are_scalars_and_bounded() -> None:
    out = _clean_detail({"n": 3, "ok": True, "gone": None, "long": "x" * 500, "obj": {"a": 1}})
    assert out is not None
    assert out["n"] == 3 and out["ok"] is True and out["gone"] is None
    assert isinstance(out["long"], str) and len(out["long"]) == 200
    assert out["obj"] == "{'a': 1}"
