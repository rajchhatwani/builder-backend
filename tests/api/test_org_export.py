"""Per-org data export (PLATFORM_SAAS_PLAN §9 "customer data export is per-org", §11).

One owner-only, session-only endpoint hands the owner everything the platform holds about their
org as one JSON file: people, projects with their specs, policies, plan and the org's audit
trail. It never contains a credential, a hash, another org's data, or a customer secret (§7.1).
"""

import json

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import platform_security as sec
from app.models.enums import PlatformRole
from app.models.platform import AuditLog
from tests.api._auth_helpers import make_auth, make_entity
from tests.api.conftest import ClientFor

Factory = async_sessionmaker[AsyncSession]
SMTP_PASSWORD = "smtp-pass-EXPORT-CANARY"


async def _acme(client_for: ClientFor) -> tuple[AsyncClient, AsyncClient, str, str]:
    owner = await client_for("owner@example.com")
    org = (await owner.post("/orgs", json={"name": "Acme", "slug": "acme"})).json()["id"]
    bob = await client_for("bob@example.com")
    inv = await owner.post(
        "/orgs/acme/invitations", json={"email": "bob@example.com", "role": "admin"}
    )
    await bob.post("/orgs/invitations/accept", json={"token": inv.json()["token"]})
    pid = (await owner.post("/projects", json={"name": "Shop", "organization_id": org})).json()[
        "id"
    ]
    await make_entity(owner, pid, "Customer")
    await make_auth(owner, pid)
    await owner.put(
        f"/projects/{pid}/auth/secrets",
        json={"smtp": {"username": "mailer", "password": SMTP_PASSWORD}},
    )
    return owner, bob, org, pid


async def test_the_owner_gets_one_json_file_with_everything(client_for: ClientFor) -> None:
    owner, _bob, org, pid = await _acme(client_for)
    r = await owner.get("/orgs/acme/export")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    assert 'attachment; filename="acme-export-' in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "no-store"
    doc = r.json()
    assert doc["format"] == "builder-org-export/1"
    assert doc["organization"]["id"] == org and doc["organization"]["slug"] == "acme"
    assert doc["organization"]["policies"] == {
        "require_mfa": False,
        "session_ttl_hours": None,
        "allow_impersonation": True,
    }
    assert {m["email"]: m["role"] for m in doc["members"]} == {
        "owner@example.com": "owner",
        "bob@example.com": "admin",
    }
    assert doc["plan"]["plan_id"] == "team"
    project = doc["projects"][0]
    assert project["id"] == pid and project["name"] == "Shop"
    assert [e["name"] for e in project["spec"]["entities"]] == ["Customer"]
    assert {m["email"] for m in project["members"]} == {"owner@example.com"}
    assert any(a["action"] == "org.created" for a in doc["audit"])


async def test_no_credential_hash_or_customer_secret_is_in_the_file(
    client_for: ClientFor,
) -> None:
    owner, _bob, _org, _pid = await _acme(client_for)
    text = (await owner.get("/orgs/acme/export")).text
    assert SMTP_PASSWORD not in text
    for forbidden in (
        "password_hash",
        "token_hash",
        "bearer_hash",
        "totp_secret",
        "recovery",
        "stripe_customer_id",
        "stripe_subscription_id",
        "client_secret",
        "idp_cert",
        "scrypt",
    ):
        assert forbidden not in text, forbidden
    # the owner's own invitation token (shown once, stored as a hash) is not in there either
    assert "bb_" not in text


async def test_only_owners_may_export(client_for: ClientFor) -> None:
    owner, bob, _org, _pid = await _acme(client_for)
    admin = await bob.get("/orgs/acme/export")  # bob is an admin, not an owner
    assert admin.status_code == 403 and admin.json()["code"] == "org_role_required"
    stranger = await client_for("eve@example.com")
    assert (await stranger.get("/orgs/acme/export")).status_code == 404
    assert (await owner.get("/orgs/acme/export")).status_code == 200


async def test_an_api_token_cannot_export(client_for: ClientFor) -> None:
    owner, _bob, _org, _pid = await _acme(client_for)
    created = await owner.post("/account/tokens", json={"name": "ci", "scopes": ["read", "write"]})
    assert created.status_code == 201, created.text
    token = AsyncClient(
        transport=owner._transport,  # type: ignore[attr-defined]
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {created.json()['token']}"},
    )
    r = await token.get("/orgs/acme/export")
    assert r.status_code == 403 and r.json()["code"] == "session_required"
    await token.aclose()


async def test_a_platform_operator_cannot_export_a_customer_org(client_for: ClientFor) -> None:
    await _acme(client_for)
    ops = await client_for(
        "ops@example.com", PlatformRole.platform_admin, audience=sec.AUDIENCE_ADMIN
    )
    assert (
        await ops.get("/orgs/acme/export")
    ).status_code == 401  # admin tokens are not customer tokens


async def test_each_export_is_audited_without_content(
    client_for: ClientFor, session_factory: Factory
) -> None:
    owner, _bob, org, _pid = await _acme(client_for)
    await owner.get("/orgs/acme/export")
    async with session_factory() as s:
        row = (
            await s.execute(select(AuditLog).where(AuditLog.action == "org.exported"))
        ).scalar_one()
    assert str(row.organization_id) == org and row.actor_email == "owner@example.com"
    assert row.detail == {"members": 2, "projects": 1, "audit_entries": row.detail["audit_entries"]}  # type: ignore[index]
    assert SMTP_PASSWORD not in json.dumps(row.detail)


async def test_other_orgs_are_not_in_the_file(client_for: ClientFor) -> None:
    owner, _bob, _org, _pid = await _acme(client_for)
    other = await client_for("zed@example.com")
    await other.post("/orgs", json={"name": "Other", "slug": "other"})
    text = (await owner.get("/orgs/acme/export")).text
    assert "zed@example.com" not in text and '"other"' not in text


async def test_an_org_waiting_for_deletion_can_still_be_exported(client_for: ClientFor) -> None:
    """Data portability matters most when the org is about to go."""
    owner, _bob, _org, _pid = await _acme(client_for)
    assert (await owner.delete("/orgs/acme")).status_code == 202
    assert (await owner.get("/orgs/acme/projects")).status_code == 423
    assert (await owner.get("/orgs/acme/export")).status_code == 200
