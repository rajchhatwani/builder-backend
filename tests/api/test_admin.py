"""The admin console: separate sign-in, role-limited actions, safety rails, privacy line."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.core import platform_security as sec
from app.main import app
from app.models.enums import PlatformRole
from app.models.platform import AuditLog, PlatformUser, ProjectMember
from app.models.project import Project
from app.services.platform_auth_service import PlatformAuthService
from tests.api._auth_helpers import make_project
from tests.api.conftest import TEST_PASSWORD, ClientFor, MakeUser

ADMIN = PlatformRole.platform_admin
SUPPORT = PlatformRole.platform_support
A = sec.AUDIENCE_ADMIN


async def admin_client(client_for: ClientFor, email: str = "root@example.com") -> AsyncClient:
    return await client_for(email, ADMIN, audience=A)


# -- sign-in --------------------------------------------------------------------------------


async def test_customers_cannot_sign_in_to_the_admin_console(
    anon_client: AsyncClient, make_user: MakeUser
) -> None:
    await make_user("cust@example.com")
    await make_user("root@example.com", ADMIN)
    bad = await anon_client.post(
        "/admin/login", json={"email": "cust@example.com", "password": TEST_PASSWORD}
    )
    assert bad.status_code == 401 and bad.json()["code"] == "invalid_credentials"
    good = await anon_client.post(
        "/admin/login", json={"email": "root@example.com", "password": TEST_PASSWORD}
    )
    assert good.status_code == 200
    cookie = good.headers["set-cookie"].lower()
    assert "bb_admin_refresh=" in cookie and "path=/admin" in cookie and "httponly" in cookie


async def test_admin_session_works_on_admin_routes_only(
    anon_client: AsyncClient, make_user: MakeUser
) -> None:
    await make_user("root@example.com", ADMIN)
    token = (
        await anon_client.post(
            "/admin/login", json={"email": "root@example.com", "password": TEST_PASSWORD}
        )
    ).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    assert (await anon_client.get("/admin/stats", headers=h)).status_code == 200
    assert (await anon_client.get("/projects", headers=h)).status_code == 401
    assert (await anon_client.get("/account/me", headers=h)).status_code == 401


async def test_admin_refresh_cycle(anon_client: AsyncClient, make_user: MakeUser) -> None:
    await make_user("root@example.com", ADMIN)
    await anon_client.post(
        "/admin/login", json={"email": "root@example.com", "password": TEST_PASSWORD}
    )
    assert (
        await anon_client.post("/admin/refresh", headers={"X-Requested-With": "builder"})
    ).status_code == 200
    assert (await anon_client.post("/admin/refresh")).status_code == 403  # no CSRF header


async def test_api_tokens_are_never_accepted_by_the_admin_console(
    client_for: ClientFor, anon_client: AsyncClient
) -> None:
    root = await client_for("root@example.com", ADMIN)  # customer-audience session of an admin
    token = (
        await root.post("/account/tokens", json={"name": "x", "scopes": ["read", "write"]})
    ).json()["token"]
    assert (
        await anon_client.get("/admin/stats", headers={"Authorization": f"Bearer {token}"})
    ).status_code == 401


# -- permissions ----------------------------------------------------------------------------


async def test_support_is_read_only(client_for: ClientFor, make_user: MakeUser) -> None:
    support = await client_for("support@example.com", SUPPORT, audience=A)
    target = await make_user("cust@example.com")
    assert (await support.get("/admin/users")).status_code == 200
    assert (await support.get("/admin/audit")).status_code == 200
    assert (await support.get("/admin/projects")).status_code == 200
    for method, path, body in (
        ("POST", "/admin/users", {"email": "new@example.com"}),
        ("PATCH", f"/admin/users/{target.id}", {"status": "suspended"}),
        ("POST", f"/admin/users/{target.id}/revoke-sessions", None),
        ("POST", f"/admin/users/{target.id}/reset-password", None),
    ):
        r = await support.request(method, path, json=body)
        assert r.status_code == 403, f"{method} {path} -> {r.status_code}"


async def test_customer_audience_with_admin_role_is_not_enough(client_for: ClientFor) -> None:
    c = await client_for("root@example.com", ADMIN)  # no audience=admin
    assert (await c.get("/admin/users")).status_code == 401


async def test_role_is_read_from_the_database_not_the_token(
    client_for: ClientFor, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    admin = await admin_client(client_for)
    assert (await admin.get("/admin/users")).status_code == 200
    async with session_factory() as s:
        row = await s.get(PlatformUser, admin.user.id)  # type: ignore[attr-defined]
        assert row is not None
        row.platform_role = PlatformRole.customer
        await s.commit()
    assert (
        await admin.get("/admin/users")
    ).status_code == 403  # demoted: the old token loses power at once


# -- user management ------------------------------------------------------------------------


async def test_create_user_with_generated_temporary_password(
    client_for: ClientFor, anon_client: AsyncClient
) -> None:
    admin = await admin_client(client_for)
    r = await admin.post("/admin/users", json={"email": "Fresh@Example.com", "name": "Fresh"})
    assert r.status_code == 201
    body = r.json()
    temp = body["temporary_password"]
    assert (
        body["user"]["email"] == "fresh@example.com"
        and body["user"]["must_change_password"] is True
    )
    assert sec.password_problems(temp, "fresh@example.com") == []
    assert r.headers["cache-control"] == "no-store"
    login = await anon_client.post(
        "/account/login", json={"email": "fresh@example.com", "password": temp}
    )
    assert login.status_code == 200 and login.json()["user"]["must_change_password"] is True
    again = await admin.post("/admin/users", json={"email": "fresh@example.com"})
    assert again.status_code == 409


async def test_admin_chosen_password_is_not_echoed(client_for: ClientFor) -> None:
    admin = await admin_client(client_for)
    r = await admin.post(
        "/admin/users", json={"email": "x@example.com", "password": "chosen-passphrase-42"}
    )
    assert r.status_code == 201 and r.json()["temporary_password"] is None
    assert "chosen-passphrase-42" not in r.text


async def test_suspend_kills_sessions_and_blocks_login(
    client_for: ClientFor, anon_client: AsyncClient, make_user: MakeUser
) -> None:
    admin = await admin_client(client_for)
    cust = await client_for("cust@example.com")
    assert (await cust.get("/projects")).status_code == 200
    r = await admin.patch(f"/admin/users/{cust.user.id}", json={"status": "suspended"})  # type: ignore[attr-defined]
    assert r.status_code == 200 and r.json()["status"] == "suspended"
    assert (await cust.get("/projects")).status_code == 401
    login = await anon_client.post(
        "/account/login", json={"email": "cust@example.com", "password": TEST_PASSWORD}
    )
    assert login.status_code == 401
    r = await admin.patch(f"/admin/users/{cust.user.id}", json={"status": "active"})  # type: ignore[attr-defined]
    assert r.status_code == 200
    assert (
        await anon_client.post(
            "/account/login", json={"email": "cust@example.com", "password": TEST_PASSWORD}
        )
    ).status_code == 200


async def test_reset_password_forces_a_change(
    client_for: ClientFor, anon_client: AsyncClient
) -> None:
    admin = await admin_client(client_for)
    cust = await client_for("cust@example.com")
    temp = (await admin.post(f"/admin/users/{cust.user.id}/reset-password")).json()[
        "temporary_password"
    ]  # type: ignore[attr-defined]
    assert (await cust.get("/projects")).status_code == 401  # old sessions are gone
    assert (
        await anon_client.post(
            "/account/login", json={"email": "cust@example.com", "password": TEST_PASSWORD}
        )
    ).status_code == 401
    login = await anon_client.post(
        "/account/login", json={"email": "cust@example.com", "password": temp}
    )
    assert login.status_code == 200 and login.json()["user"]["must_change_password"] is True


async def test_safety_rails(client_for: ClientFor) -> None:
    admin = await admin_client(client_for)
    me = admin.user.id  # type: ignore[attr-defined]
    for body in ({"status": "suspended"}, {"platform_role": "customer"}):
        r = await admin.patch(f"/admin/users/{me}", json=body)
        assert r.status_code == 409 and r.json()["code"] == "self_change"
    assert (await admin.post(f"/admin/users/{me}/reset-password")).status_code == 409
    # Support (read-only) cannot change an administrator either.
    support = await client_for("support@example.com", SUPPORT, audience=A)
    r = await support.patch(f"/admin/users/{me}", json={"platform_role": "customer"})
    assert r.status_code == 403


async def test_an_admin_cannot_remove_the_last_admin_even_by_demoting_themselves(
    client_for: ClientFor,
) -> None:
    first = await admin_client(client_for, "first@example.com")
    second = await admin_client(client_for, "second@example.com")
    assert (
        await first.patch(f"/admin/users/{second.user.id}", json={"platform_role": "customer"})
    ).status_code == 200  # type: ignore[attr-defined]
    # `second` was demoted, so `first` is the only admin and cannot step down or suspend themselves
    # (self_change). `last_admin` in AdminService is the second line of defence behind that rule.
    assert (
        await first.patch(f"/admin/users/{first.user.id}", json={"status": "suspended"})
    ).status_code == 409  # type: ignore[attr-defined]


async def test_list_users_filters_and_paginates(client_for: ClientFor, make_user: MakeUser) -> None:
    admin = await admin_client(client_for)
    for i in range(3):
        await make_user(f"user{i}@example.com")
    r = await admin.get("/admin/users", params={"q": "user", "limit": 2})
    body = r.json()
    assert body["total"] == 3 and len(body["items"]) == 2
    assert "password_hash" not in r.text and "hash" not in r.text.lower()
    assert (await admin.get("/admin/users", params={"role": "platform_admin"})).json()["total"] == 1
    assert (await admin.get("/admin/users", params={"limit": 10_000})).status_code == 422


# -- privacy line, audit, stats -------------------------------------------------------------


async def test_admin_sees_project_metadata_but_not_content(client_for: ClientFor) -> None:
    admin = await admin_client(client_for)
    cust = await client_for("cust@example.com")
    p = await make_project(cust, "Secret Shop")
    await cust.post(f"/projects/{p}/entities", json={"name": "Salaries"})
    listing = await admin.get("/admin/projects")
    item = listing.json()["items"][0]
    assert (
        item["name"] == "Secret Shop"
        and item["owner_emails"] == ["cust@example.com"]
        and item["entity_count"] == 1
    )
    assert "Salaries" not in listing.text
    # No route gives an administrator the customer's spec, entities, secrets or generated code.
    for path in (
        f"/projects/{p}",
        f"/projects/{p}/spec",
        f"/projects/{p}/entities",
        f"/projects/{p}/generate/download",
    ):
        assert (await admin.get(path)).status_code == 401, path


async def test_admin_actions_are_audited_and_visible(
    client_for: ClientFor, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    admin = await admin_client(client_for)
    cust = await client_for("cust@example.com")
    await admin.patch(f"/admin/users/{cust.user.id}", json={"status": "suspended"})  # type: ignore[attr-defined]
    r = await admin.get("/admin/audit", params={"action": "admin."})
    items = r.json()["items"]
    assert [i["action"] for i in items] == ["admin.user_update"]
    assert items[0]["actor_email"] == "root@example.com" and items[0]["detail"] == {
        "status": "suspended"
    }
    denied = await admin.get("/admin/audit", params={"result": "denied"})
    assert denied.status_code == 200


async def test_stats(client_for: ClientFor, make_user: MakeUser) -> None:
    admin = await admin_client(client_for)
    await make_user("a@example.com")
    s = (await admin.get("/admin/stats")).json()
    assert s["users"] == 2 and s["admins"] == 1 and s["active_users"] == 2


async def test_settings_are_read_only_and_expose_no_secrets(client_for: ClientFor) -> None:
    admin = await admin_client(client_for)
    r = await admin.get("/admin/settings")
    assert r.status_code == 200
    text = r.text.lower()
    assert "database" not in text and "password" not in text and "secret" not in text
    assert (await admin.put("/admin/settings", json={})).status_code == 405


# -- bootstrap ------------------------------------------------------------------------------


async def test_bootstrap_creates_one_admin_and_adopts_unclaimed_projects(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s:
        s.add_all([Project(name="Old", slug="old"), Project(name="Older", slug="older")])
        await s.commit()
    settings = Settings(
        bootstrap_admin_email="Boss@Example.com", bootstrap_admin_password="a-long-bootstrap-pass"
    )  # type: ignore[arg-type]
    async with session_factory() as s:
        created = await PlatformAuthService(s, settings).bootstrap_admin()
    assert created is not None and created.email == "boss@example.com"
    async with session_factory() as s:
        members = list((await s.execute(select(ProjectMember))).scalars())
        assert len(members) == 2 and {m.role.value for m in members} == {"owner"}
        assert {m.user_id for m in members} == {created.id}
        # idempotent: a second start changes nothing
        assert await PlatformAuthService(s, settings).bootstrap_admin() is None
        assert len(list((await s.execute(select(PlatformUser))).scalars())) == 1
        actions = [a for (a,) in (await s.execute(select(AuditLog.action))).all()]
        assert actions == ["admin.bootstrap"]


async def test_bootstrap_without_configuration_does_nothing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as s:
        assert await PlatformAuthService(s, Settings()).bootstrap_admin() is None


async def test_bootstrap_password_is_not_logged_or_stored_in_clear(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = Settings(
        bootstrap_admin_email="boss@example.com", bootstrap_admin_password="a-long-bootstrap-pass"
    )  # type: ignore[arg-type]
    assert "a-long-bootstrap-pass" not in repr(settings)
    async with session_factory() as s:
        await PlatformAuthService(s, settings).bootstrap_admin()
        user = (await s.execute(select(PlatformUser))).scalar_one()
    assert "a-long-bootstrap-pass" not in user.password_hash and user.password_hash.startswith(
        "scrypt$"
    )


@pytest.fixture(autouse=True)
def _default_settings() -> None:
    app.dependency_overrides.pop(get_settings, None)
