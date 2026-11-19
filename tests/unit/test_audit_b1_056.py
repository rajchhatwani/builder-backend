"""Audit B1-056: generated auth module fixes (F-0285..F-0292), checked on the templates."""

import asyncio
import datetime as dt
import importlib.abc
import importlib.util
import math
import re
import sys
import types
from pathlib import Path
from typing import Any

import pytest

TPL = Path("app/core/generator/features/auth/templates")


class AppError(Exception):
    """Stand-in for the generated project's app.core.errors.AppError."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code, self.status_code = code, status_code


_errors = types.ModuleType("app.core.errors")
_errors.AppError = AppError  # type: ignore[attr-defined]


def _load(name: str, path: Path) -> Any:
    sys.modules.setdefault("app.core.errors", sys.modules.get("app.core.errors") or _errors)
    sys.modules["app.core.errors"] = _errors
    spec = importlib.util.spec_from_file_location(name, path, loader=_PyLoader(name, path))
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class _PyLoader(importlib.abc.SourceLoader):
    def __init__(self, name: str, path: Path) -> None:
        self.name, self.path = name, str(path)

    def get_filename(self, fullname: str) -> str:
        return self.path

    def get_data(self, path: str) -> bytes:
        return Path(path).read_bytes()


@pytest.fixture(scope="module")
def ratelimit() -> Any:
    return _load("b1056_ratelimit", TPL / "app/auth/ratelimit.py.tpl")


@pytest.mark.parametrize("bad", ["0/hour", "5/0minutes", "0/0hour", "x/hour"])
def test_parse_limit_refuses_zero(ratelimit: Any, bad: str) -> None:  # F-0285
    with pytest.raises(ValueError):
        ratelimit.parse_limit(bad)


def test_parse_limit_valid(ratelimit: Any) -> None:
    assert ratelimit.parse_limit("5/15minutes") == (5, 900)
    assert ratelimit.parse_limit("10/hour") == (10, 3600)


class _Req:
    client = type("C", (), {"host": "1.2.3.4"})()


async def _call(limiter: Any, fail: bool, gate: asyncio.Event) -> int:
    gen = limiter(_Req())
    try:
        await gen.__anext__()
    except AppError as exc:
        return exc.status_code
    await gate.wait()
    try:
        if fail:
            await gen.athrow(AppError("invalid_credentials", "bad", 401))
        else:
            await gen.aclose()
    except AppError as exc:
        return exc.status_code
    return 200


async def test_failure_limiter_counts_concurrent_burst(ratelimit: Any) -> None:  # F-0287
    limiter = ratelimit.FailureRateLimiter("t", "5/15minutes")
    gate = asyncio.Event()
    tasks = [asyncio.create_task(_call(limiter, True, gate)) for _ in range(30)]
    await asyncio.sleep(0.05)
    gate.set()
    codes = await asyncio.gather(*tasks)
    # B1-031: calls in flight are capped at count + _INFLIGHT_EXTRA (so overlapping valid sign-ins
    # never 429), so a parallel burst may land that many attempts before the first failure counts.
    admitted = 5 + ratelimit.FailureRateLimiter._INFLIGHT_EXTRA
    assert codes.count(401) <= admitted
    assert codes.count(429) >= 30 - admitted
    # once those failures have landed the client is blocked
    assert await _call(limiter, True, asyncio.Event()) == 429


async def test_failure_limiter_success_does_not_use_budget(ratelimit: Any) -> None:
    limiter = ratelimit.FailureRateLimiter("t2", "2/minute")
    gate = asyncio.Event()
    gate.set()
    for _ in range(6):
        assert await _call(limiter, False, gate) == 200


def _coerce() -> Any:
    src = (TPL / "keycloak/app/auth/oidc.py.tpl").read_text()
    start = src.index("_INT_RE = ")
    end = (
        src.index("\ndef ", src.index("def coerce_attribute") + 1)
        if "\ndef " in src[src.index("def coerce_attribute") + 1 :]
        else len(src)
    )
    ns: dict[str, Any] = {"re": re, "dt": dt, "math": math, "Any": Any}
    exec(src[start:end], ns)  # noqa: S102
    return ns["coerce_attribute"]


@pytest.mark.parametrize("value", ["3000000000", 3000000000, "-3000000000", 2**31])
def test_coerce_integer_refuses_beyond_32_bit(value: Any) -> None:  # F-0290
    assert _coerce()("integer", value, None, ()) is None


@pytest.mark.parametrize(
    ("value", "want"), [("2147483647", 2147483647), (-(2**31), -(2**31)), ("9", 9)]
)
def test_coerce_integer_in_range(value: Any, want: int) -> None:
    assert _coerce()("integer", value, None, ()) == want


def _src(rel: str) -> str:
    return (TPL / rel).read_text()


def test_password_hashing_is_off_the_event_loop() -> None:  # F-0288
    service = _src("app/auth/service.py.tpl")
    assert not re.search(r"(?<!await )security\.(hash|verify)_password\(", service)
    assert "to_thread" in _src("app/auth/security.py.j2")


def test_refresh_reuse_ends_the_identity_session() -> None:  # F-0286
    assert "family_id=row.family_id" in _src("app/auth/tokens.py.j2")
    assert "family_id=uuid.UUID(result[1])" in _src("app/auth/tokens.py.j2")
    service = _src("app/auth/service.py.tpl")
    assert '"refresh_reuse"' in service


def test_delivery_is_not_awaited_inline() -> None:  # F-0289
    service = _src("app/auth/service.py.tpl")
    assert "ensure_future" in service
    assert "            await send()\n        except" not in service


def test_backchannel_logout_records_unseen_session() -> None:  # F-0291
    assert "user_id=user_id" in _src("keycloak/app/auth/router.py.j2")
    identity = _src("app/auth/identity.py.tpl")
    assert "revoked_at=_now()," in identity.split("async def end_session")[1].split("result =")[0]


def test_delete_account_erases_identity_emails() -> None:  # F-0292
    assert "erase_emails" in _src("keycloak/app/auth/service.py.tpl")
    assert "email_at_link=None" in _src("app/auth/identity.py.tpl")


def test_generated_keycloak_tests_cover_unseen_logout_and_email_erase() -> None:  # F-0878
    gen = _src("keycloak/tests/test_identity.py.j2")
    unseen = gen.split("async def test_back_channel_logout_before_first_use")[1].split("async def ")[0]
    assert 'sid="never-seen", sub="bc-early"' in unseen and "== 401" in unseen
    erase = gen.split("async def test_deleting_the_account_erases")[1].split("async def ")[0]
    assert 'client.delete("/auth/me"' in erase and "email_at_link is None" in erase
