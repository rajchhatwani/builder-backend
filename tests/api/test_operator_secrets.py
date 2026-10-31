"""§7.1 "what operators cannot see", checked across the whole admin surface (Phase F).

Plants a distinct canary in every kind of customer secret the platform stores (project SMTP
password, OIDC client secret, SCIM bearer, personal access token, invitation token, TOTP secret,
recovery code, password), then walks EVERY `/admin` route with real ids - read routes directly,
and "view as" through a minted impersonation token - and fails if a canary shows up in any body.
The route list comes from tests/api/_routes.py, so a route added later is covered without edits.
"""
# ruff: noqa: F811  (the `dns` fixture is imported, then used as a parameter)

import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import platform_security as sec
from app.main import app
from app.models.enums import PlatformRole
from tests.api._auth_helpers import make_auth, make_entity, make_project
from tests.api._mfa_helpers import enroll
from tests.api._routes import all_routes
from tests.api.conftest import TEST_PASSWORD, ClientFor, TotpClock
from tests.api.test_scim import dns, enterprise_org  # noqa: F401
from tests.api.test_sso_config import OIDC_CONFIG

pytestmark = pytest.mark.usefixtures("dns")

SMTP_PASSWORD = "smtp-CANARY-71c2"
OIDC_SECRET = "oidc-CANARY-55ab"


async def _plant(owner: AsyncClient, factory, dns, totp_clock: TotpClock) -> dict[str, str]:  # type: ignore[no-untyped-def]
    org = await enterprise_org(owner, factory, dns, "leaky", "leaky.test")
    pid = (await owner.post("/projects", json={"name": "Leaky", "organization_id": org})).json()[
        "id"
    ]
    await make_entity(owner, pid, "Secretive")
    await make_auth(owner, pid)
    await owner.put(
        f"/projects/{pid}/auth/secrets", json={"smtp": {"username": "m", "password": SMTP_PASSWORD}}
    )
    await owner.put("/orgs/leaky/sso", json={**OIDC_CONFIG, "oidc_client_secret": OIDC_SECRET})
    canaries = {
        "smtp": SMTP_PASSWORD,
        "oidc": OIDC_SECRET,
        "scim": (await owner.post("/orgs/leaky/scim/token")).json()["token"],
        "pat": (
            await owner.post("/account/tokens", json={"name": "ci", "scopes": ["read"]})
        ).json()["token"],
        "invite": (
            await owner.post(
                "/orgs/leaky/invitations", json={"email": "i@leaky.test", "role": "member"}
            )
        ).json()["token"],
        "password": TEST_PASSWORD,
    }
    secret, recovery = await enroll(owner, totp_clock)
    canaries["totp"], canaries["recovery"] = secret, recovery[0]
    canaries["_org"], canaries["_project"] = org, pid
    return canaries


def _fill(path: str, ids: dict[str, str]) -> str:
    return re.sub(r"{(\w+)}", lambda m: ids.get(m.group(1), str(uuid.uuid4())), path)


async def test_no_admin_read_route_shows_a_customer_secret(
    client_for: ClientFor,
    session_factory,
    dns,
    totp_clock: TotpClock,  # type: ignore[no-untyped-def]
) -> None:
    owner = await client_for("owner@leaky.test")
    planted = await _plant(owner, session_factory, dns, totp_clock)
    org, pid = planted.pop("_org"), planted.pop("_project")
    ops = await client_for(
        "ops@example.com", PlatformRole.platform_admin, audience=sec.AUDIENCE_ADMIN
    )
    ids = {"org_id": org, "user_id": str(owner.user.id), "project_id": pid}  # type: ignore[attr-defined]
    # the admin sees the project through its own routes; token ids come from the owner's list
    ids["token_id"] = (await owner.get("/account/tokens")).json()[0]["id"]

    walked, leaks = 0, []
    for route in all_routes():
        if not route.path.startswith("/admin/") or route.method != "GET":
            continue
        r = await ops.get(_fill(route.path, ids))
        walked += 1
        assert r.status_code < 500, f"GET {route.path} -> {r.status_code}"
        for name, value in planted.items():
            if value in r.text:
                leaks.append(f"{name} in GET {route.path}")
    assert walked >= 15, f"walked only {walked} admin read routes"
    assert leaks == []


async def test_a_view_as_session_never_returns_a_secret_or_a_credential(
    client_for: ClientFor,
    session_factory,
    dns,
    totp_clock: TotpClock,  # type: ignore[no-untyped-def]
) -> None:
    """Consent lets an operator see what the member sees - not the credentials the platform
    keeps for them. Every GET route reachable with the token, writes switched ON, is walked."""
    owner = await client_for("owner@leaky.test")
    planted = await _plant(owner, session_factory, dns, totp_clock)
    org, pid = planted.pop("_org"), planted.pop("_project")
    # the viewing token is for the OWNER (so they are a project member); the secrets are theirs
    ops = await client_for(
        "ops@example.com", PlatformRole.platform_admin, audience=sec.AUDIENCE_ADMIN
    )
    started = await ops.post(
        f"/admin/organizations/{org}/members/{owner.user.id}/impersonate",  # type: ignore[attr-defined]
        json={"reason": "walk every route"},
    )
    assert started.status_code == 201, started.text
    viewer = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {started.json()['access_token']}"},
    )
    await viewer.post("/account/impersonation/writes", json={"enabled": True})
    ids = {"slug": "leaky", "project_id": pid, "org_id": org, "user_id": str(owner.user.id)}  # type: ignore[attr-defined]

    leaks, reached = [], 0
    for route in all_routes():
        if route.path.startswith(("/admin", "/scim", "/sso", "/mcp", "/.well-known")):
            continue
        if route.method != "GET":
            continue
        r = await viewer.get(_fill(route.path, ids))
        assert r.status_code < 500, f"GET {route.path} -> {r.status_code}"
        if r.status_code == 200:
            reached += 1
        for name, value in planted.items():
            if value in r.text:
                leaks.append(f"{name} in GET {route.path}")
    await viewer.aclose()
    assert reached >= 10, f"only {reached} routes answered 200"
    assert leaks == []


async def test_the_viewing_token_is_not_in_any_listing(
    client_for: ClientFor,
    session_factory,
    dns,
    totp_clock: TotpClock,  # type: ignore[no-untyped-def]
) -> None:
    owner = await client_for("owner@leaky.test")
    planted = await _plant(owner, session_factory, dns, totp_clock)
    ops = await client_for(
        "ops@example.com", PlatformRole.platform_admin, audience=sec.AUDIENCE_ADMIN
    )
    started = await ops.post(
        f"/admin/organizations/{planted['_org']}/members/{owner.user.id}/impersonate",  # type: ignore[attr-defined]
        json={"reason": "check listings"},
    )
    token = started.json()["access_token"]
    for path in (
        "/admin/impersonation/sessions",
        "/admin/audit",
        f"/admin/organizations/{planted['_org']}",
    ):
        assert token not in (await ops.get(path)).text
    assert token not in (await owner.get("/orgs/leaky/audit")).text
    _ = (make_project, planted)
