"""Adversarial review: operator console authz (REQ-§2.2, §7, §7.1).
Run: uv run python -m pytest review/tests/test_adv_admin.py -p no:cacheprovider -q
"""
import json
import pathlib
import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core import platform_security as sec
from app.main import app
from app.models.enums import PlatformRole
from tests.api.conftest import ClientFor, bearer_for

ROWS = json.loads(pathlib.Path("review/artifacts/routes.json").read_text())
ADMIN = [r for r in ROWS if r["guard"] == "admin"]


def fill(path: str) -> str:
    return re.sub(r"{(\w+)}", lambda m: str(uuid.uuid4()) if m.group(1).endswith("id") else "x", path)


async def as_(user, audience=sec.AUDIENCE_ADMIN):  # noqa: ANN001
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver",
                       headers=bearer_for(user, audience, amr=["pwd", "otp"]))


async def test_support_is_read_only_everywhere(make_user, override_session) -> None:  # noqa: ANN001
    sup = await make_user("support@example.com", PlatformRole.platform_support)
    bad = []
    async with await as_(sup) as c:
        for r in ADMIN:
            if r["path"] in ("/admin/login", "/admin/refresh", "/admin/logout") or "/login/mfa" in r["path"]:
                continue
            resp = await c.request(r["method"], fill(r["path"]), json={})
            if r["method"] not in ("GET",) and resp.status_code != 403:
                bad.append((r["method"], r["path"], resp.status_code))
            if r["method"] == "GET" and resp.status_code >= 500:
                bad.append((r["method"], r["path"], resp.status_code))
    assert bad == [], bad


async def test_customer_and_wrong_audience_cannot_reach_admin(make_user, override_session) -> None:  # noqa: ANN001
    cust = await make_user("cust@example.com", PlatformRole.customer)
    adm = await make_user("adm@example.com", PlatformRole.platform_admin)
    bad = []
    skip = ("/admin/login", "/admin/refresh", "/admin/logout")
    for who, aud in [(cust, sec.AUDIENCE_ADMIN), (cust, sec.AUDIENCE_APP), (adm, sec.AUDIENCE_APP)]:
        async with await as_(who, aud) as c:
            for r in ADMIN:
                if r["path"].startswith(skip) or "/login/" in r["path"]:
                    continue
                resp = await c.request(r["method"], fill(r["path"]), json={})
                if resp.status_code not in (401, 403):
                    bad.append((who.email, aud, r["method"], r["path"], resp.status_code))
    assert bad == [], bad[:10]


async def test_admin_token_does_not_work_on_customer_surface(make_user, override_session) -> None:  # noqa: ANN001
    adm = await make_user("adm2@example.com", PlatformRole.platform_admin)
    async with await as_(adm) as c:
        for p in ["/orgs", "/projects", "/account/me"]:
            r = await c.get(p)
            assert r.status_code in (401, 403), (p, r.status_code)


async def test_admin_without_mfa_amr_is_refused(make_user, override_session) -> None:  # noqa: ANN001
    """REQ-§4.4 'Platform-admin accounts require MFA at all times'."""
    adm = await make_user("adm3@example.com", PlatformRole.platform_admin)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver",
                           headers=bearer_for(adm, sec.AUDIENCE_ADMIN, amr=["pwd"])) as c:
        r = await c.get("/admin/users")
        assert r.status_code in (401, 403), ("admin token with amr=pwd only accepted", r.status_code)


async def test_operator_views_never_expose_secrets(client_for: ClientFor, make_user, override_session, session_factory) -> None:  # noqa: ANN001
    """REQ-§7.1: no spec / credentials / secrets in any operator response."""
    owner = await client_for("cust-owner@example.com")
    org = (await owner.post("/orgs", json={"name": "Secretive", "slug": "secretive"})).json()
    async with session_factory() as s:
        await s.execute(text("update subscriptions set plan_id='enterprise' where organization_id=:o"), {"o": org["id"]})
        await s.commit()
    pr = (await owner.post("/projects", json={"name": "TOPSECRETNAME", "slug": "tsn", "organization_id": org["id"]})).json()
    # plant secrets the operator must never see
    await owner.put(f"/projects/{pr['id']}/auth/secrets", json={"smtp_password": "SMTP-PASS-CANARY-123"})
    await owner.put("/orgs/secretive/scim", json={}) if False else None
    tok = await owner.post("/orgs/secretive/scim/token")
    scim_raw = tok.json().get("token", "")
    adm = await make_user("op2@example.com", PlatformRole.platform_admin)
    out = {}
    async with await as_(adm) as c:
        for p in ["/admin/organizations", f"/admin/organizations/{org['id']}", "/admin/projects", f"/admin/projects/{pr['id']}",
                  "/admin/users", "/admin/audit", "/admin/stats", "/admin/billing", "/admin/insights", "/admin/plans"]:
            r = await c.get(p)
            out[p] = (r.status_code, r.text)
    for p, (code, body) in out.items():
        for canary in ["SMTP-PASS-CANARY-123", scim_raw, "scrypt$", "password_hash", "totp_secret", "bearer_hash", "oidc_client_secret", "idp_cert_pem"]:
            if canary and canary in body:
                pytest.fail(f"{p} ({code}) leaks {canary[:12]}")
