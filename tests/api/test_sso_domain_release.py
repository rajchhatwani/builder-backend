# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)
"""Review F-008: a verified SSO domain claim can be freed by a platform admin."""

import uuid

import pytest
from httpx import AsyncClient

from app.core import platform_security as sec
from app.models.enums import PlatformRole
from tests.api.conftest import ClientFor
from tests.api.test_scim import actions
from tests.api.test_sso_config import dns, set_plan, verified_domain  # noqa: F401
from tests.api.test_sso_login import acme_saml  # noqa: F401  (fixture)

pytestmark = pytest.mark.usefixtures("dns")


async def _staff(client_for: ClientFor, role: PlatformRole, email: str) -> AsyncClient:
    return await client_for(email, role, audience=sec.AUDIENCE_ADMIN)


async def test_a_verified_claim_blocks_other_orgs_until_released(
    client: AsyncClient,
    client_for: ClientFor,
    session_factory,
    dns,
    acme_saml: str,  # noqa: ANN001,F811
) -> None:
    other = await client_for("new-owner@example.com")
    org2 = (await other.post("/orgs", json={"name": "New", "slug": "new-co"})).json()["id"]
    await set_plan(session_factory, org2, "business")
    taken = await other.post("/orgs/new-co/sso/domains", json={"domain": "acme.test"})
    assert taken.status_code == 409 and taken.json()["code"] == "domain_taken"

    support = await _staff(client_for, PlatformRole.platform_support, "support@example.com")
    admin = await _staff(client_for, PlatformRole.platform_admin, "ops@example.com")
    assert (
        await support.post("/admin/sso/domains/acme.test/release", json={"reason": "x"})
    ).status_code == 403
    customer = await client.post("/admin/sso/domains/acme.test/release", json={"reason": "x"})
    assert customer.status_code in (401, 403)
    assert (await admin.post("/admin/sso/domains/acme.test/release", json={})).status_code == 422

    r = await admin.post("/admin/sso/domains/ACME.test/release", json={"reason": "domain sold"})
    assert r.status_code == 200 and r.json()["id"] == acme_saml, r.text
    # the old holder's SSO went off with its last verified domain
    assert (await client.get("/orgs/acme/sso")).json()["active"] is False
    assert (await client.get("/orgs/acme/sso")).json()["domains"] == []
    logged = await actions(session_factory, "admin.sso_domain_released")
    assert len(logged) == 1
    assert logged[0].detail["reason"] == "domain sold"
    assert logged[0].detail["was_verified"] is True and logged[0].detail["sso_deactivated"] is True

    # ...and the new owner of the domain can now verify it
    assert (await verified_domain(other, dns, "acme.test", "new-co"))["verified_at"] is not None


async def test_release_of_an_unknown_domain_is_404(client_for: ClientFor) -> None:
    admin = await _staff(client_for, PlatformRole.platform_admin, "ops@example.com")
    r = await admin.post("/admin/sso/domains/nowhere.test/release", json={"reason": "x"})
    assert r.status_code == 404
    assert (
        await admin.post(f"/admin/sso/domains/{uuid.uuid4()}/release", json={"reason": "x"})
    ).status_code in (404, 422)
