"""Phase D.1–D.2 + gate: an org admin configures SSO, claims and DNS-verifies e-mail domains, and
activates the connection. `plans.allow_sso` gates it with the usual 402 + `quota.denied` (§6.2)."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import crypto
from app.models.platform import AuditLog, Subscription
from app.models.sso import SsoConnection, SsoDomain
from app.services import dns_txt
from tests.api.conftest import ClientFor
from tests.sso_fake_idp import IDP_ENTITY_ID, IDP_SSO_URL, idp_keys

Factory = async_sessionmaker[AsyncSession]

SAML_CONFIG = {
    "protocol": "saml",
    "idp_entity_id": IDP_ENTITY_ID,
    "idp_sso_url": IDP_SSO_URL,
    "idp_cert_pem": None,  # filled per test (key generation is cached)
}
OIDC_CONFIG = {
    "protocol": "oidc",
    "oidc_discovery_url": "https://login.oidc.example.test/.well-known/openid-configuration",
    "oidc_client_id": "builder-client",
    "oidc_client_secret": "super-secret-value-123",
}


def saml_config() -> dict[str, object]:
    return {**SAML_CONFIG, "idp_cert_pem": idp_keys().cert_pem}


async def set_plan(factory: Factory, org_id: str, plan: str) -> None:
    async with factory() as session:
        sub = await session.get(Subscription, uuid.UUID(org_id))
        assert sub is not None
        sub.plan_id = plan
        await session.commit()


async def business_org(client: AsyncClient, factory: Factory, slug: str = "acme") -> str:
    org = (await client.post("/orgs", json={"name": slug.title(), "slug": slug})).json()["id"]
    await set_plan(factory, org, "business")
    return org


@pytest.fixture
def dns(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    records: dict[str, list[str]] = {}

    async def fake(name: str) -> list[str]:
        return records.get(name, [])

    monkeypatch.setattr(dns_txt, "txt_records", fake)
    return records


async def verified_domain(
    client: AsyncClient, dns: dict[str, list[str]], domain: str = "acme.test", slug: str = "acme"
) -> dict[str, object]:
    added = await client.post(f"/orgs/{slug}/sso/domains", json={"domain": domain})
    assert added.status_code == 201, added.text
    body = added.json()
    dns[body["dns_record_name"]] = ["some-other=record", body["dns_record_value"]]
    r = await client.post(f"/orgs/{slug}/sso/domains/{domain}/verify")
    assert r.status_code == 200, r.text
    return r.json()


# -- read ---------------------------------------------------------------------------------


async def test_unconfigured_sso_shows_sp_details(
    client: AsyncClient, session_factory: Factory
) -> None:
    await business_org(client, session_factory)
    r = await client.get("/orgs/acme/sso")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["configured"] is False
    assert body["allowed_by_plan"] is True
    assert body["sp"]["entity_id"].endswith("/sso/metadata/acme")
    assert body["sp"]["acs_url"].endswith("/sso/saml/acme/acs")
    assert body["sp"]["oidc_redirect_uri"].endswith("/sso/oidc/acme/callback")
    assert body["domains"] == []


async def test_members_cannot_see_sso(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory
) -> None:
    await business_org(client, session_factory)
    bob = await client_for("bob@example.com")
    inv = await client.post(
        "/orgs/acme/invitations", json={"email": "bob@example.com", "role": "member"}
    )
    await bob.post("/orgs/invitations/accept", json={"token": inv.json()["token"]})
    r = await bob.get("/orgs/acme/sso")
    assert r.status_code == 403
    assert r.json()["code"] == "org_role_required"


# -- plan gate ------------------------------------------------------------------------------


async def test_sso_needs_a_plan_that_allows_it(
    client: AsyncClient, session_factory: Factory
) -> None:
    org = (await client.post("/orgs", json={"name": "Acme", "slug": "acme"})).json()["id"]
    # 'team' has allow_sso = false
    r = await client.put("/orgs/acme/sso", json=saml_config())
    assert r.status_code == 402, r.text
    body = r.json()
    assert body["code"] == "sso_not_in_plan"
    assert body["details"][0]["reason"] == "feature"
    assert body["details"][0]["resource"] == "sso"
    assert body["details"][0]["organization_slug"] == "acme"
    assert (
        await client.post("/orgs/acme/sso/domains", json={"domain": "acme.test"})
    ).status_code == 402
    assert (await client.get("/orgs/acme/sso")).json()["allowed_by_plan"] is False
    async with session_factory() as session:
        denied = (
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "quota.denied",
                        AuditLog.organization_id == uuid.UUID(org),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert denied and denied[0].detail["resource"] == "sso"  # type: ignore[index]


async def test_personal_orgs_cannot_have_sso(client: AsyncClient) -> None:
    personal = next(
        o for o in (await client.get("/orgs")).json()["items"] if o["kind"] == "personal"
    )
    r = await client.put(f"/orgs/{personal['slug']}/sso", json=saml_config())
    assert r.status_code == 409
    assert r.json()["code"] == "sso_not_for_personal_orgs"


# -- configuration --------------------------------------------------------------------------


async def test_saml_config_is_saved_and_summarised(
    client: AsyncClient, session_factory: Factory
) -> None:
    org = await business_org(client, session_factory)
    r = await client.put("/orgs/acme/sso", json={**saml_config(), "jit_role": "admin"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["configured"] is True and body["active"] is False
    assert body["protocol"] == "saml"
    assert body["idp_entity_id"] == IDP_ENTITY_ID
    assert body["jit_role"] == "admin" and body["jit_enabled"] is True
    assert len(body["idp_certificate"]["sha256_fingerprint"]) == 95
    assert "idp_cert_pem" not in body
    async with session_factory() as session:
        audit = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action == "sso.config_updated",
                    AuditLog.organization_id == uuid.UUID(org),
                )
            )
        ).scalar_one()
        assert "BEGIN CERTIFICATE" not in str(audit.detail)


async def test_bad_saml_config_is_refused(client: AsyncClient, session_factory: Factory) -> None:
    await business_org(client, session_factory)
    bad_cert = {**saml_config(), "idp_cert_pem": "not a certificate"}
    r = await client.put("/orgs/acme/sso", json=bad_cert)
    assert r.status_code == 422 and r.json()["code"] == "invalid_certificate"
    missing = {**saml_config(), "idp_sso_url": None}
    assert (await client.put("/orgs/acme/sso", json=missing)).status_code == 422
    insecure = {**saml_config(), "idp_sso_url": "http://idp.example.test/sso"}
    r = await client.put("/orgs/acme/sso", json=insecure)
    assert r.status_code == 422 and r.json()["code"] == "insecure_url"
    owner_jit = {**saml_config(), "jit_role": "owner"}
    assert (await client.put("/orgs/acme/sso", json=owner_jit)).status_code == 422


async def test_oidc_secret_is_encrypted_and_never_returned(
    client: AsyncClient, session_factory: Factory
) -> None:
    org = await business_org(client, session_factory)
    r = await client.put("/orgs/acme/sso", json=OIDC_CONFIG)
    assert r.status_code == 200, r.text
    assert r.json()["oidc_client_secret_set"] is True
    assert "super-secret-value-123" not in r.text
    assert "super-secret-value-123" not in (await client.get("/orgs/acme/sso")).text
    async with session_factory() as session:
        conn = (
            await session.execute(
                select(SsoConnection).where(SsoConnection.organization_id == uuid.UUID(org))
            )
        ).scalar_one()
        assert conn.oidc_client_secret_enc is not None
        assert b"super-secret-value-123" not in conn.oidc_client_secret_enc
        assert crypto.decrypt(conn.oidc_client_secret_enc.decode()) == "super-secret-value-123"
        rows = (await session.execute(select(AuditLog))).scalars().all()
        assert all("super-secret-value-123" not in str(a.detail) for a in rows)

    # Updating without a secret keeps the stored one; first OIDC save needs one.
    keep = {k: v for k, v in OIDC_CONFIG.items() if k != "oidc_client_secret"}
    assert (await client.put("/orgs/acme/sso", json={**keep, "oidc_client_id": "c2"})).json()[
        "oidc_client_secret_set"
    ] is True
    await client.put("/orgs/acme/sso", json=saml_config())  # switch protocol: OIDC fields go
    r = await client.put("/orgs/acme/sso", json=keep)
    assert r.status_code == 422 and r.json()["code"] == "oidc_client_secret_required"


async def test_api_tokens_cannot_change_sso(client: AsyncClient, session_factory: Factory) -> None:
    await business_org(client, session_factory)
    token = (
        await client.post("/account/tokens", json={"name": "ci", "scopes": ["read", "write"]})
    ).json()["token"]
    r = await client.put(
        "/orgs/acme/sso", json=saml_config(), headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403
    assert r.json()["code"] == "session_required"


# -- domains --------------------------------------------------------------------------------


async def test_domain_is_claimed_then_verified_over_dns(
    client: AsyncClient, session_factory: Factory, dns: dict[str, list[str]]
) -> None:
    await business_org(client, session_factory)
    r = await client.post("/orgs/acme/sso/domains", json={"domain": " Acme.TEST. "})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["domain"] == "acme.test"
    assert body["verified_at"] is None
    assert body["dns_record_type"] == "TXT"
    assert body["dns_record_name"] == "_builder-verification.acme.test"
    assert body["dns_record_value"].startswith("builder-verification=")

    # Not in DNS yet: refused with the record to add, and the attempt is audited.
    r = await client.post("/orgs/acme/sso/domains/acme.test/verify")
    assert r.status_code == 409
    assert r.json()["code"] == "domain_not_verified"
    assert r.json()["details"][0]["dns_record_value"] == body["dns_record_value"]

    dns[body["dns_record_name"]] = [body["dns_record_value"]]
    r = await client.post("/orgs/acme/sso/domains/acme.test/verify")
    assert r.status_code == 200 and r.json()["verified_at"]
    listed = (await client.get("/orgs/acme/sso")).json()["domains"]
    assert [d["domain"] for d in listed] == ["acme.test"] and listed[0]["verified_at"]
    async with session_factory() as session:
        actions = [
            a.action
            for a in (await session.execute(select(AuditLog).order_by(AuditLog.id))).scalars()
        ]
        assert "sso.domain_added" in actions and "sso.domain_verified" in actions


@pytest.mark.parametrize(
    "domain", ["gmail.com", "outlook.com", "localhost", "no_dots", "a..b.com", "-x.com"]
)
async def test_unclaimable_domains(
    client: AsyncClient, session_factory: Factory, domain: str
) -> None:
    await business_org(client, session_factory)
    r = await client.post("/orgs/acme/sso/domains", json={"domain": domain})
    assert r.status_code == 422, r.text


async def test_verified_domain_belongs_to_one_org(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory, dns: dict[str, list[str]]
) -> None:
    await business_org(client, session_factory)
    await verified_domain(client, dns)
    other = await client_for("eve@example.com")
    await business_org(other, session_factory, slug="evil")
    r = await other.post("/orgs/evil/sso/domains", json={"domain": "acme.test"})
    assert r.status_code == 409
    assert r.json()["code"] == "domain_taken"


async def test_unverified_claim_does_not_block_the_real_owner(
    client: AsyncClient, client_for: ClientFor, session_factory: Factory, dns: dict[str, list[str]]
) -> None:
    """Squatting: org 'evil' claims acme.test first but can't prove it; Acme can still take it."""
    squatter = await client_for("eve@example.com")
    await business_org(squatter, session_factory, slug="evil")
    squat = (await squatter.post("/orgs/evil/sso/domains", json={"domain": "acme.test"})).json()
    await business_org(client, session_factory)
    mine = await client.post("/orgs/acme/sso/domains", json={"domain": "acme.test"})
    assert mine.status_code == 201
    # Tokens are per org: the squatter's TXT value can never verify Acme and vice versa.
    assert mine.json()["dns_record_value"] != squat["dns_record_value"]
    dns[mine.json()["dns_record_name"]] = [squat["dns_record_value"]]
    assert (await client.post("/orgs/acme/sso/domains/acme.test/verify")).status_code == 409
    dns[mine.json()["dns_record_name"]] = [mine.json()["dns_record_value"]]
    assert (await client.post("/orgs/acme/sso/domains/acme.test/verify")).status_code == 200
    # The squatter's claim is gone.
    assert (await squatter.post("/orgs/evil/sso/domains/acme.test/verify")).status_code == 404


async def test_remove_domain(
    client: AsyncClient, session_factory: Factory, dns: dict[str, list[str]]
) -> None:
    await business_org(client, session_factory)
    await verified_domain(client, dns)
    await client.put("/orgs/acme/sso", json=saml_config())
    assert (await client.post("/orgs/acme/sso/activate")).status_code == 200
    # The last verified domain of an active connection stays until SSO is turned off.
    r = await client.delete("/orgs/acme/sso/domains/acme.test")
    assert r.status_code == 409 and r.json()["code"] == "last_verified_domain"
    assert (await client.post("/orgs/acme/sso/deactivate")).status_code == 200
    assert (await client.delete("/orgs/acme/sso/domains/acme.test")).status_code == 204
    async with session_factory() as session:
        assert (await session.execute(select(SsoDomain))).scalars().all() == []


# -- activation -----------------------------------------------------------------------------


async def test_activation_needs_config_and_a_verified_domain(
    client: AsyncClient, session_factory: Factory, dns: dict[str, list[str]]
) -> None:
    org = await business_org(client, session_factory)
    r = await client.post("/orgs/acme/sso/activate")
    assert r.status_code == 409 and r.json()["code"] == "sso_not_configured"
    await client.put("/orgs/acme/sso", json=saml_config())
    r = await client.post("/orgs/acme/sso/activate")
    assert r.status_code == 409 and r.json()["code"] == "no_verified_domain"
    await verified_domain(client, dns)
    r = await client.post("/orgs/acme/sso/activate")
    assert r.status_code == 200 and r.json()["active"] is True

    # Downgrade: activation is gated again (402); an active connection can still be turned off.
    await client.post("/orgs/acme/sso/deactivate")
    await set_plan(session_factory, org, "team")
    r = await client.post("/orgs/acme/sso/activate")
    assert r.status_code == 402 and r.json()["code"] == "sso_not_in_plan"
    assert (await client.post("/orgs/acme/sso/deactivate")).status_code == 200


async def test_delete_connection(
    client: AsyncClient, session_factory: Factory, dns: dict[str, list[str]]
) -> None:
    await business_org(client, session_factory)
    await client.put("/orgs/acme/sso", json=saml_config())
    assert (await client.delete("/orgs/acme/sso")).status_code == 204
    assert (await client.get("/orgs/acme/sso")).json()["configured"] is False
    assert (await client.delete("/orgs/acme/sso")).status_code == 404


async def test_sp_metadata_is_public_xml(
    anon_client: AsyncClient, client: AsyncClient, session_factory: Factory
) -> None:
    await business_org(client, session_factory)
    r = await anon_client.get("/sso/metadata/acme")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/samlmetadata+xml")
    assert 'entityID="http://localhost:8000/sso/metadata/acme"' in r.text
    assert (await anon_client.get("/sso/metadata/nope")).status_code == 404


async def test_trust_unverified_email_is_off_by_default_and_kept_when_omitted(
    client: AsyncClient, session_factory: Factory
) -> None:
    await business_org(client, session_factory)
    first = await client.put("/orgs/acme/sso", json=OIDC_CONFIG)
    assert first.status_code == 200 and first.json()["trust_unverified_email"] is False
    on = await client.put("/orgs/acme/sso", json={**OIDC_CONFIG, "trust_unverified_email": True})
    assert on.json()["trust_unverified_email"] is True
    kept = await client.put("/orgs/acme/sso", json=OIDC_CONFIG)  # an older client omits it
    assert kept.json()["trust_unverified_email"] is True
    assert (await client.get("/orgs/acme/sso")).json()["trust_unverified_email"] is True
    async with session_factory() as session:
        row = (
            (await session.execute(select(AuditLog).where(AuditLog.action == "sso.config_updated")))
            .scalars()
            .all()
        )
        assert any(a.detail.get("trust_unverified_email") is True for a in row)  # type: ignore[union-attr]
