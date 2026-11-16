"""Shared/rate-limiter keys: one tenant's traffic must not consume another tenant's budget, and a
caller must not choose which bucket it lands in."""

import pytest
from httpx import AsyncClient

from app.api import security
from app.config import get_settings
from tests.api.conftest import ClientFor
from tests.api.test_requirements import provider  # noqa: F401


def _login(c: AsyncClient, ip: str, email: str = "nobody@example.com"):  # noqa: ANN202
    return c.post(
        "/account/login", json={"email": email, "password": "wrong-password-123"},
        headers={"X-Forwarded-For": ip},
    )


async def test_spoofed_forwarded_for_cannot_dodge_the_auth_limit(
    anon_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BUILDER_TRUST_PROXY_HEADERS", "false")
    get_settings.cache_clear()
    security.reset_auth_limiter()
    limit = get_settings().auth_rate_limit_attempts
    codes = [(await _login(anon_client, f"10.9.{i // 250}.{i % 250}")).status_code for i in range(limit + 5)]
    assert 429 in codes, "rotating X-Forwarded-For gave every request a fresh bucket"
    get_settings.cache_clear()


async def test_with_a_trusted_proxy_the_client_cannot_prepend_its_way_out(
    anon_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BUILDER_TRUST_PROXY_HEADERS", "true")
    get_settings.cache_clear()
    security.reset_auth_limiter()
    limit = get_settings().auth_rate_limit_attempts
    # the proxy appends the real peer last; the attacker varies only what is in front of it
    codes = [(await _login(anon_client, f"1.2.3.{i % 250}, 203.0.113.7")).status_code for i in range(limit + 5)]
    assert 429 in codes
    # a different real peer (the victim) is not throttled by the attacker's bucket
    ok = await _login(anon_client, "9.9.9.9, 198.51.100.20", "victim-login@example.com")
    assert ok.status_code != 429, ok.text + str(dict(ok.headers))
    get_settings.cache_clear()


async def test_intake_budget_of_one_tenant_does_not_throttle_another(
    client_for: ClientFor, provider: object
) -> None:
    from app.services.requirements import service as rs
    from tests.api._auth_helpers import make_project
    from tests.api.test_requirements import intake

    a = await client_for("victim@example.com")
    b = await client_for("attacker@example.com")
    pa, pb = await make_project(a, "V"), await make_project(b, "M")
    codes = [(await intake(b, pb, prompt=f"Invoice flow {i}")).status_code for i in range(rs._limiter.attempts + 2)]
    assert 429 in codes, "attacker never hit the per-project budget (test would be vacuous)"
    ok = await intake(a, pa, prompt="Invoice flow")
    assert ok.status_code == 200, ok.text
    # and the attacker's budget is unaffected by what the victim did on a project they do not share
    assert (await intake(b, pa, prompt="x")).status_code in (403, 404)
