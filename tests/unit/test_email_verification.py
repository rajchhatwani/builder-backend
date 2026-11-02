"""CO3-7 unit tests: the verification mail, the token format and the verified-e-mail gate."""

import asyncio
from types import SimpleNamespace

import pytest

from app.api.deps import require_verified_email
from app.config import Settings
from app.core import platform_security as sec
from app.exceptions import AppError
from app.models.enums import PlatformRole
from app.services import mail_service
from app.services.platform_auth_service import PlatformAuthService


def _principal(verified: object, role: PlatformRole = PlatformRole.customer) -> SimpleNamespace:
    return SimpleNamespace(user=SimpleNamespace(email_verified_at=verified, platform_role=role))


def test_unverified_customer_is_refused() -> None:
    with pytest.raises(AppError) as err:
        asyncio.run(require_verified_email(_principal(None)))  # type: ignore[arg-type]
    assert err.value.status_code == 403 and err.value.code == "email_not_verified"


def test_verified_customer_and_staff_pass() -> None:
    ok = _principal("2026-01-01")
    assert asyncio.run(require_verified_email(ok)) is ok  # type: ignore[arg-type]
    staff = _principal(None, PlatformRole.platform_admin)
    assert asyncio.run(require_verified_email(staff)) is staff  # type: ignore[arg-type]


def test_verification_url_uses_the_app_url() -> None:
    svc = PlatformAuthService(None, Settings(public_app_url="https://app.example/"))  # type: ignore[arg-type]
    assert svc.verification_url("tok") == "https://app.example/verify-email?token=tok"


def test_hash_is_sha256_hex_and_compare_is_exact() -> None:
    digest = sec.hash_token("bb_ev_abc")
    assert len(digest) == 64 and "bb_ev_abc" not in digest
    assert sec.tokens_equal(digest, sec.hash_token("bb_ev_abc"))
    assert not sec.tokens_equal(digest, sec.hash_token("bb_ev_abd"))


def test_verification_mail_carries_the_link_and_goes_through_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[tuple[str, str, str]] = []

    async def fake_send(to: str, subject: str, body: str) -> bool:
        sent.append((to, subject, body))
        return True

    monkeypatch.setattr(mail_service, "send", fake_send)
    assert asyncio.run(mail_service.send_verification(to="a@b.test", url="https://x/y", hours=24))
    assert sent[0][0] == "a@b.test" and "https://x/y" in sent[0][2] and "24 hours" in sent[0][2]
