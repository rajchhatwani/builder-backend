"""Review F-003: a NUL character in input is a 422, never a 500 from the database."""

import pytest
from httpx import AsyncClient

from tests.api.conftest import ClientFor
from tests.api.test_scim import SCIM, enterprise_org, scim_token, user_body
from tests.api.test_sso_config import dns  # noqa: F401  (fixture)

NUL = "a\x00b"


async def test_register_with_a_nul_byte_is_422(anon_client: AsyncClient) -> None:
    for body in (
        {"email": f"{NUL}@example.com", "password": "correct horse battery 1", "name": "x"},
        {"email": "ok@example.com", "password": "correct horse battery 1", "name": NUL},
    ):
        r = await anon_client.post("/account/register", json=body)
        assert r.status_code == 422 and r.json()["code"] == "validation_error", r.text


@pytest.mark.parametrize("path", ["/account/login", "/account/login/discover", "/admin/login"])
async def test_public_endpoints_answer_422(anon_client: AsyncClient, path: str) -> None:
    r = await anon_client.post(path, json={"email": f"{NUL}@example.com", "password": NUL})
    assert r.status_code == 422, r.text


async def test_org_and_project_names_with_a_nul_byte_are_422(client_for: ClientFor) -> None:
    u = await client_for("nul@example.com")
    assert (await u.post("/orgs", json={"name": NUL, "slug": "nul-co"})).status_code == 422
    assert (await u.post("/projects", json={"name": NUL, "slug": "nulp"})).status_code == 422
    assert (
        await u.post("/account/tokens", json={"name": NUL, "scopes": ["read"]})
    ).status_code == 422


async def test_nul_in_the_query_string_is_422(client_for: ClientFor) -> None:
    u = await client_for("nul@example.com")
    assert (await u.get("/orgs?q=a%00b")).status_code == 422


async def test_scim_username_with_a_nul_byte_is_a_4xx(
    client_for: ClientFor,
    anon_client: AsyncClient,
    session_factory,
    dns,  # noqa: ANN001,F811
) -> None:
    owner = await client_for("nul-owner@example.com")
    await enterprise_org(owner, session_factory, dns, "nul-co", "alpha.test")
    h = await scim_token(owner, "nul-co")
    r = await anon_client.post(f"{SCIM}/Users", json=user_body("a\x00b@alpha.test"), headers=h)
    assert 400 <= r.status_code < 500, r.text


async def test_escaped_backslash_before_u0000_is_not_a_nul(client_for: ClientFor) -> None:
    u = await client_for("nul@example.com")
    r = await u.post(
        "/account/tokens",
        content='{"name": "back\\\\u0000slash", "scopes": ["read"]}',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 201, r.text


async def test_ordinary_unicode_still_works(client_for: ClientFor) -> None:
    u = await client_for("nul@example.com")
    r = await u.post("/orgs", json={"name": "Café Ünïcode 日本", "slug": "cafe-co"})
    assert r.status_code == 201, r.text
