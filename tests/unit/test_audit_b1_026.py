"""Audit B1-026 regressions: effect-hook fingerprint, OIDC URL guard / body cap, digest injection."""

import httpx
import pytest
from pydantic import ValidationError

from app.exceptions import AppError
from app.models.behavior_config import ProjectBehavior
from app.schemas.account import ImpersonationRequest
from app.services import behavior_service as bsvc
from app.services import oidc
from app.services import impersonation_digest

HOOK = {
    "name": "notify",
    "effects": ["webhook"],
    "reads": ["Order"],
    "input": {"a": 1},
    "point": "after_create",
}


def _row() -> ProjectBehavior:
    return ProjectBehavior(sections={"hooks": [HOOK]}, version=1)


@pytest.mark.parametrize(
    "change",
    [
        {"reads": ["Order", "Customer"]},
        {"input": {"a": 1, "b": 2}},
        {"point": "before_delete"},
    ],
)
def test_editor_cannot_widen_an_approved_effect_hook(change: dict) -> None:  # F-0235
    token = bsvc.ACTOR_ROLE.set("editor")
    try:
        with pytest.raises(AppError) as err:
            bsvc._guard_effects(_row(), "hooks", [{**HOOK, **change}])
        assert err.value.status_code == 403
    finally:
        bsvc.ACTOR_ROLE.reset(token)


def test_editor_may_still_resave_an_unchanged_effect_hook() -> None:  # F-0235 control
    token = bsvc.ACTOR_ROLE.set("editor")
    try:
        bsvc._guard_effects(_row(), "hooks", [dict(HOOK)])
    finally:
        bsvc.ACTOR_ROLE.reset(token)


def test_editor_cannot_turn_an_effectless_hook_into_one_with_wider_reads() -> None:  # F-0235
    row = ProjectBehavior(sections={"hooks": [{**HOOK, "effects": []}]}, version=1)
    token = bsvc.ACTOR_ROLE.set("editor")
    try:
        with pytest.raises(AppError):
            bsvc._guard_effects(row, "hooks", [dict(HOOK)])
    finally:
        bsvc.ACTOR_ROLE.reset(token)


@pytest.mark.parametrize("host", ["64:ff9b::a00:5", "64:ff9b::a9fe:a9fe", "2002:a00:5::1"])
async def test_oidc_guard_rejects_embedded_private_ipv4(host: str) -> None:  # F-0238
    with pytest.raises(oidc.OidcError) as err:
        await oidc.check_outbound_url(
            f"https://[{host}]/", allow_private=False, require_https=True
        )
    assert err.value.args[0] == "private_address" or "private_address" in str(err.value)


async def test_oidc_guard_still_accepts_a_public_address() -> None:  # F-0238 control
    out = await oidc.check_outbound_url(
        "https://[2606:4700:4700::1111]/", allow_private=False, require_https=True
    )
    assert out


async def test_oidc_response_is_cut_off_while_streaming(monkeypatch: pytest.MonkeyPatch) -> None:
    pulled = 0
    total = 400

    async def body():  # noqa: ANN202
        nonlocal pulled
        for _ in range(total):
            pulled += 1
            yield b"x" * 8192

    monkeypatch.setattr(
        oidc,
        "TRANSPORT",
        httpx.MockTransport(lambda r: httpx.Response(200, content=body())),
    )
    with pytest.raises(oidc.OidcError):
        await oidc._request(
            "GET", "https://idp.example/x", allow_private=True, require_https=True
        )
    assert pulled < total // 2  # F-0239: stopped near the 512 KiB cap, not after reading it all


async def test_oidc_content_length_over_cap_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        oidc,
        "TRANSPORT",
        httpx.MockTransport(
            lambda r: httpx.Response(200, headers={"content-length": str(10_000_000)}, content=b"x")
        ),
    )
    with pytest.raises(oidc.OidcError):
        await oidc._request(
            "GET", "https://idp.example/x", allow_private=True, require_https=True
        )


@pytest.mark.parametrize("reason", ["ticket 1\n0 session(s), 0 refused", "ticket\r\nforged", "abc\x00def ok"])
def test_impersonation_reason_rejects_control_characters(reason: str) -> None:  # F-0241
    with pytest.raises(ValidationError):
        ImpersonationRequest(reason=reason)


def test_impersonation_reason_plain_text_ok() -> None:  # F-0241 control
    assert ImpersonationRequest(reason="  ticket 4411: customer cannot log in ").reason.startswith(
        "ticket 4411"
    )


def test_digest_text_escapes_newlines_and_chat_mentions() -> None:  # F-0241
    out = impersonation_digest._clean('x"\n0 session(s) <!channel> <@U1> & y')
    assert "\n" not in out and "<" not in out and ">" not in out
