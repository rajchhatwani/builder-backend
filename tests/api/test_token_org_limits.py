"""Review F-002: an API token never performs destructive or owner-level org actions."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import platform_authz as authz
from app.main import app
from tests.api.conftest import ClientFor


async def _pat(owner: AsyncClient, scopes: list[str]) -> AsyncClient:
    r = await owner.post("/account/tokens", json={"name": "t", "scopes": scopes})
    assert r.status_code == 201, r.text
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {r.json()['token']}"},
    )


def test_session_only_routes_are_all_listed_org_routes() -> None:
    assert set(authz.ORG_ROUTE_ROLES) >= authz.ORG_ROUTES_SESSION_ONLY


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("DELETE", "/orgs/tok-co", None),
        ("POST", "/orgs/tok-co/deletion/cancel", None),
        ("PATCH", "/orgs/tok-co/members/00000000-0000-0000-0000-000000000000", {"role": "admin"}),
        ("DELETE", "/orgs/tok-co/members/00000000-0000-0000-0000-000000000000", None),
        ("POST", "/orgs/tok-co/transfer", {"user_id": "00000000-0000-0000-0000-000000000000"}),
        ("POST", "/orgs/tok-co/billing/checkout", {"plan_id": "team"}),
        ("POST", "/orgs/tok-co/billing/portal", None),
        (
            "POST",
            "/orgs/tok-co/projects/00000000-0000-0000-0000-000000000000/transfer",
            {"organization_slug": "x"},
        ),
    ],
)
async def test_write_token_is_refused_on_session_only_routes(
    client_for: ClientFor, method: str, path: str, body: dict | None
) -> None:
    owner = await client_for("tok-owner@example.com")
    assert (await owner.post("/orgs", json={"name": "Tok", "slug": "tok-co"})).status_code == 201
    async with await _pat(owner, ["read", "write"]) as pat:
        r = await pat.request(method, path, json=body)
    assert r.status_code == 403 and r.json()["code"] == "session_required", r.text
    # the org is untouched
    assert (await owner.get("/orgs/tok-co")).json()["deletion_scheduled_for"] is None


async def test_write_token_can_still_do_ordinary_org_writes(client_for: ClientFor) -> None:
    owner = await client_for("tok-owner@example.com")
    await owner.post("/orgs", json={"name": "Tok", "slug": "tok-co"})
    async with await _pat(owner, ["write"]) as pat:
        assert (await pat.patch("/orgs/tok-co", json={"name": "Renamed"})).status_code == 200
        assert (await pat.post("/orgs", json={"name": "Two", "slug": "tok-two"})).status_code == 201


async def test_read_only_token_cannot_create_orgs_or_accept_invitations(
    client_for: ClientFor,
) -> None:
    owner = await client_for("tok-owner@example.com")
    async with await _pat(owner, ["read"]) as pat:
        made = await pat.post("/orgs", json={"name": "Nope", "slug": "nope-co"})
        by_token = await pat.post("/orgs/invitations/accept", json={"token": "x" * 20})
        by_id = await pat.post("/orgs/invitations/00000000-0000-0000-0000-000000000000/accept")
        listing = await pat.get("/orgs")
    for r in (made, by_token, by_id):
        assert r.status_code == 403 and r.json()["code"] == "insufficient_scope", r.text
    assert listing.status_code == 200
    assert (await owner.get("/orgs/nope-co")).status_code == 404
