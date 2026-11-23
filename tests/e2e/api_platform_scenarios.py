"""Scenario for the API platform (copied into the generated `api_shop` project's tests/ by
tests/e2e/test_api_platform_stack.py and run against a real Postgres).

An administrator issues a key and installs an app; an integration reads Products through the public API. Proves, over
the whole flow and with raw SQL: the unlisted column (Product.internal_cost) never leaves, the plaintext key and the app
token are in no table (only hashes), and an uninstall cuts the app off at once."""

import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from app.db import session_factory
from app.models.products import Product
from tests._auth_support import authed_client, client_for, outbox  # noqa: F401

MARKER = 987_654_321


async def test_issue_read_install_uninstall(
    authed_client: AsyncClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLATFORM_SIGNING_KEY", "scenario-signing-key-" + "z" * 24)
    async with session_factory() as session:
        tenant = (await session.execute(sa.text("SELECT tenant_id FROM auth_users LIMIT 1"))).scalar_one()
        session.add(Product(title="Marker mug", price_cents=1200, internal_cost=MARKER, tenant_id=tenant))
        await session.commit()
    created = (
        await authed_client.post("/platform/keys", json={"name": "shop sync", "scopes": ["Product"], "environment": "prod"})
    ).json()
    installed = (await authed_client.post("/platform/apps/storefront/install", json={})).json()
    async with client_for({"X-API-Key": created["key"]}) as http:
        response = await http.get("/public/v1/products")
        assert response.status_code == 200
        rows = response.json()
        assert [r["title"] for r in rows] == ["Marker mug"] and set(rows[0]) == {"id", "title", "price_cents"}
        assert str(MARKER) not in response.text
        assert (await http.get("/public/v1/reviews")).status_code == 403
    async with client_for({"X-API-Key": installed["token"]}) as app_client:
        assert (await app_client.get("/public/v1/products")).status_code == 200
        assert (await authed_client.post("/platform/apps/storefront/uninstall")).status_code == 200
        assert (await app_client.get("/public/v1/products")).status_code == 401
    async with session_factory() as session:
        tables = [r[0] for r in await session.execute(sa.text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))]
        for secret in (created["key"], installed["token"], installed["signing_secret"]):
            for table in tables:
                count = (await session.execute(sa.text(f'SELECT count(*) FROM "{table}" AS x WHERE x::text LIKE :p'), {"p": f"%{secret}%"})).scalar_one()
                assert count == 0, table
        hashes = (await session.execute(sa.text("SELECT count(*) FROM api_keys WHERE length(key_hash) = 64"))).scalar_one()
        assert hashes == 2
    assert uuid.UUID(created["id"]) != uuid.UUID(installed["installation_id"])
