"""Access control across the whole API surface.

Three kinds of test, none of which needs updating when a route is added:
  1. a structural walk of every route: nothing is reachable without a guard, and every guarded route
     is on the short unscoped list or resolves to a project (otherwise the guard fails closed);
  2. an unauthenticated sweep: every non-public route answers 401, never 404/422/500;
  3. IDOR and role sweeps with two customers: B can never see or touch A's data, and a viewer can
     never change anything.
"""

import re
import uuid

from httpx import AsyncClient

from app.api import security
from app.core import platform_authz as authz
from app.core import platform_security as sec
from app.models.enums import PlatformRole
from tests.api._auth_helpers import make_entity, make_project, make_role
from tests.api._routes import RouteInfo, all_routes
from tests.api.conftest import ClientFor, add_to_project_org

PUBLIC = {
    # RFC 9728 discovery document for MCP clients; carries no data.
    ("GET", "/.well-known/oauth-protected-resource"),
    ("GET", "/health"),
    ("GET", "/ready"),
    ("POST", "/account/register"),
    ("POST", "/account/login"),
    ("POST", "/account/refresh"),
    ("POST", "/account/logout"),
    ("POST", "/admin/login"),
    ("POST", "/admin/refresh"),
    ("POST", "/admin/logout"),
    # MFA sign-in steps (§4.4): authenticated by the short-lived challenge token in the body,
    # which only a correct password produces.
    ("POST", "/account/login/mfa"),
    ("POST", "/account/login/mfa/setup"),
    ("POST", "/account/login/mfa/enable"),
    ("POST", "/admin/login/mfa"),
    ("POST", "/admin/login/mfa/setup"),
    ("POST", "/admin/login/mfa/enable"),
    # Stripe calls it; authenticated by the Stripe-Signature HMAC, not by a session.
    ("POST", "/billing/stripe/webhook"),
    # Enterprise SSO sign-in (Phase D): before any session exists. Discovery answers only
    # about the e-mail domain; the callbacks are authenticated by the IdP's signature plus a
    # single-use, browser-bound login state.
    ("POST", "/account/login/discover"),
    ("GET", "/sso/metadata/{slug}"),
    ("GET", "/sso/{slug}/login"),
    ("POST", "/sso/saml/{slug}/acs"),
    ("GET", "/sso/oidc/{slug}/callback"),
}
ID_PARAMS = {
    "project_id",
    "entity_id",
    "field_id",
    "relation_id",
    "role_id",
    "permission_id",
    "generation_id",
}


def _routes() -> list[RouteInfo]:
    return all_routes()


def test_the_route_walker_sees_the_whole_app() -> None:
    """A walker that finds nothing makes every test below pass (review F-001)."""
    routes = _routes()
    assert len(routes) > 100
    paths = {r.path for r in routes}
    assert {"/orgs/{slug}/members", "/admin/users", "/scim/v2/Users", "/projects"} <= paths


def test_public_list_has_no_stale_entries() -> None:
    existing = {(r.method, r.path) for r in _routes()}
    assert sorted(PUBLIC - existing) == []


def test_every_route_is_guarded_or_deliberately_public() -> None:
    unguarded = []
    for route in _routes():
        if (route.method, route.path) in PUBLIC:
            continue
        ok = (
            security.guard in route.calls
            or any("require_admin" in n or "admin_principal" in n for n in route.names)
            or security.current_principal in route.calls
            or security.session_principal in route.calls
            or security.org_context in route.calls
            # SCIM 2.0 (Phase E): the org's SCIM bearer token, checked by scim_auth.
            or "scim_auth" in route.names
        )
        if not ok:
            unguarded.append(f"{route.method} {route.path}")
    assert unguarded == [], "routes reachable without authentication: " + ", ".join(unguarded)


def test_every_guarded_route_resolves_to_a_project_or_is_listed_unscoped() -> None:
    orphans = []
    for route in _routes():
        if security.guard not in route.calls:
            continue
        params = set(re.findall(r"{(\w+)}", route.path))
        if (route.method, route.path) in authz.UNSCOPED_ROUTES or params & ID_PARAMS:
            continue
        orphans.append(f"{route.method} {route.path}")
    assert orphans == [], (
        "guarded routes that name no project and are not allow-listed: " + ", ".join(orphans)
    )


def test_unscoped_allow_list_is_tiny() -> None:
    assert {("POST", "/projects"), ("GET", "/projects")} == authz.UNSCOPED_ROUTES


def _fill(path: str) -> str:
    return re.sub(r"{(\w+)}", lambda _: str(uuid.uuid4()), path)


async def test_unauthenticated_sweep_is_401_everywhere(anon_client: AsyncClient) -> None:
    offenders = []
    for route in _routes():
        if (route.method, route.path) in PUBLIC:
            continue
        r = await anon_client.request(route.method, _fill(route.path), json={})
        if r.status_code != 401:
            offenders.append(f"{route.method} {route.path} -> {r.status_code}")
    assert offenders == []


async def test_docs_are_not_exposed_outside_local() -> None:
    from app.config import Settings

    assert Settings(environment="production").docs_enabled is False
    assert Settings(environment="local").docs_enabled is True
    assert Settings(environment="production", enable_docs=True).docs_enabled is True


# -- IDOR: customer B against customer A's data ---------------------------------------------


async def _victim_world(a: AsyncClient) -> dict[str, str]:
    project = await make_project(a)
    entity = await make_entity(a, project, "Item")
    field = (
        await a.post(f"/entities/{entity}/fields", json={"name": "title", "type": "string"})
    ).json()["id"]
    role = (await make_role(a, project, name="staff"))["id"]
    return {"project_id": project, "entity_id": entity, "field_id": field, "role_id": role}


async def test_customer_b_cannot_see_or_touch_customer_a(client_for: ClientFor) -> None:
    a = await client_for("a@example.com")
    b = await client_for("b@example.com")
    world = await _victim_world(a)
    p, e, f, r = world["project_id"], world["entity_id"], world["field_id"], world["role_id"]
    attempts = [
        ("GET", f"/projects/{p}"),
        ("PATCH", f"/projects/{p}"),
        ("DELETE", f"/projects/{p}"),
        ("GET", f"/projects/{p}/entities"),
        ("POST", f"/projects/{p}/entities"),
        ("GET", f"/projects/{p}/spec"),
        ("PUT", f"/projects/{p}/spec"),
        ("POST", f"/projects/{p}/validate"),
        ("GET", f"/projects/{p}/generate/download"),
        ("POST", f"/projects/{p}/generate/preview"),
        ("GET", f"/projects/{p}/generations"),
        ("GET", f"/projects/{p}/auth"),
        ("PUT", f"/projects/{p}/auth/secrets"),
        ("GET", f"/projects/{p}/auth/secrets/status"),
        ("GET", f"/projects/{p}/roles"),
        ("GET", f"/projects/{p}/permissions"),
        ("GET", f"/projects/{p}/members"),
        ("POST", f"/projects/{p}/members"),
        ("GET", f"/projects/{p}/payments"),
        ("GET", f"/projects/{p}/storage"),
        ("GET", f"/projects/{p}/keycloak"),
        ("GET", f"/entities/{e}"),
        ("PATCH", f"/entities/{e}"),
        ("DELETE", f"/entities/{e}"),
        ("GET", f"/entities/{e}/fields"),
        ("POST", f"/entities/{e}/fields"),
        ("PATCH", f"/fields/{f}"),
        ("DELETE", f"/fields/{f}"),
        ("GET", f"/roles/{r}"),
        ("PATCH", f"/roles/{r}"),
        ("DELETE", f"/roles/{r}"),
    ]
    wrong = []
    for method, path in attempts:
        res = await b.request(method, path, json={})
        if res.status_code != 404:
            wrong.append(f"{method} {path} -> {res.status_code}")
    assert wrong == [], "B should get the same 404 as for a nonexistent id"
    # ... and A's world is untouched.
    assert (await a.get(f"/projects/{p}")).status_code == 200
    assert (await a.get(f"/entities/{e}")).status_code == 200
    # B's own list never contains A's project.
    assert (await b.get("/projects")).json()["total"] == 0


async def test_nonexistent_and_forbidden_look_identical(client_for: ClientFor) -> None:
    a = await client_for("a@example.com")
    b = await client_for("b@example.com")
    p = await make_project(a)
    theirs = await b.get(f"/projects/{p}")
    missing = await b.get(f"/projects/{uuid.uuid4()}")
    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json()


async def test_malformed_ids_do_not_crash(client: AsyncClient) -> None:
    for path in (
        "/projects/not-a-uuid",
        "/entities/12345",
        "/roles/%27%20OR%201=1--",
        "/roles/..%2f..%2fetc",
    ):
        assert (await client.get(path)).status_code in (404, 422)
    assert (await client.patch("/fields/%27%20OR%201=1--", json={})).status_code in (404, 422)


# -- roles inside a project -----------------------------------------------------------------


async def _add_member(owner: AsyncClient, project: str, email: str, role: str) -> None:
    await add_to_project_org(project, email)
    r = await owner.post(f"/projects/{project}/members", json={"email": email, "role": role})
    assert r.status_code == 201, r.text


async def test_role_matrix_on_a_shared_project(client_for: ClientFor) -> None:
    owner = await client_for("owner@example.com")
    editor = await client_for("editor@example.com")
    viewer = await client_for("viewer@example.com")
    p = await make_project(owner)
    entity = await make_entity(owner, p, "Item")
    await _add_member(owner, p, "editor@example.com", "editor")
    await _add_member(owner, p, "viewer@example.com", "viewer")

    # viewer: read everything, change nothing
    assert (await viewer.get(f"/projects/{p}")).status_code == 200
    assert (await viewer.get(f"/projects/{p}/entities")).status_code == 200
    assert (await viewer.get(f"/projects/{p}/members")).status_code == 200
    for method, path in (
        ("POST", f"/projects/{p}/entities"),
        ("PATCH", f"/entities/{entity}"),
        ("DELETE", f"/entities/{entity}"),
        ("PATCH", f"/projects/{p}"),
        ("DELETE", f"/projects/{p}"),
        ("POST", f"/projects/{p}/members"),
        ("PUT", f"/projects/{p}/auth/secrets"),
    ):
        res = await viewer.request(method, path, json={})
        assert res.status_code == 403, f"viewer {method} {path} -> {res.status_code}"

    # editor: change the model, but not membership, secrets or the project itself
    assert (await editor.post(f"/projects/{p}/entities", json={"name": "Order"})).status_code == 201
    for method, path in (
        ("DELETE", f"/projects/{p}"),
        ("POST", f"/projects/{p}/members"),
        ("PUT", f"/projects/{p}/auth/secrets"),
    ):
        res = await editor.request(method, path, json={})
        assert res.status_code == 403, f"editor {method} {path} -> {res.status_code}"

    # owner may do all of it
    assert (await owner.delete(f"/projects/{p}")).status_code == 204


async def test_denied_attempts_are_audited(client_for: ClientFor, session_factory) -> None:  # noqa: ANN001
    from sqlalchemy import select

    from app.models.platform import AuditLog

    owner = await client_for("owner@example.com")
    viewer = await client_for("viewer@example.com")
    p = await make_project(owner)
    await _add_member(owner, p, "viewer@example.com", "viewer")
    await viewer.post(f"/projects/{p}/entities", json={"name": "X"})
    async with session_factory() as s:
        rows = list(
            (await s.execute(select(AuditLog).where(AuditLog.action == "access.denied"))).scalars()
        )
    assert len(rows) == 1 and rows[0].actor_email == "viewer@example.com"
    assert str(rows[0].project_id) == p


async def test_successful_changes_are_audited_and_failed_ones_are_not(
    client: AsyncClient, session_factory
) -> None:  # noqa: ANN001
    from sqlalchemy import func, select

    from app.models.platform import AuditLog

    p = await make_project(client)
    await client.post(f"/projects/{p}/entities", json={"name": "Item"})
    failed = await client.post(f"/projects/{p}/entities", json={"name": "Item"})  # duplicate name
    assert failed.status_code >= 400
    async with session_factory() as s:
        n = (
            await s.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "project.change", AuditLog.project_id == uuid.UUID(p))
            )
        ).scalar_one()
    assert n == 1


# -- membership rules -----------------------------------------------------------------------


async def test_last_owner_cannot_leave_or_be_demoted(client_for: ClientFor) -> None:
    owner = await client_for("owner@example.com")
    p = await make_project(owner)
    me = owner.user.id  # type: ignore[attr-defined]
    assert (await owner.delete(f"/projects/{p}/members/{me}")).status_code == 409
    assert (
        await owner.patch(f"/projects/{p}/members/{me}", json={"role": "viewer"})
    ).status_code == 409
    await client_for("second@example.com")
    await _add_member(owner, p, "second@example.com", "owner")
    assert (
        await owner.patch(f"/projects/{p}/members/{me}", json={"role": "viewer"})
    ).status_code == 200


async def test_adding_unknown_or_suspended_people_looks_the_same(
    client_for: ClientFor, make_user
) -> None:  # noqa: ANN001
    from app.models.enums import AccountStatus

    owner = await client_for("owner@example.com")
    p = await make_project(owner)
    await make_user("gone@example.com", status=AccountStatus.suspended)
    await add_to_project_org(p, "nobody@example.com")
    a = await owner.post(
        f"/projects/{p}/members", json={"email": "nobody@example.com", "role": "viewer"}
    )
    await add_to_project_org(p, "gone@example.com")
    b = await owner.post(
        f"/projects/{p}/members", json={"email": "gone@example.com", "role": "viewer"}
    )
    assert a.status_code == b.status_code == 404 and a.json() == b.json()


async def test_member_added_twice_conflicts(client_for: ClientFor) -> None:
    owner = await client_for("owner@example.com")
    await client_for("x@example.com")
    p = await make_project(owner)
    await _add_member(owner, p, "x@example.com", "viewer")
    await add_to_project_org(p, "x@example.com")
    again = await owner.post(
        f"/projects/{p}/members", json={"email": "x@example.com", "role": "editor"}
    )
    assert again.status_code == 409


# -- the customer and admin surfaces are separate -------------------------------------------


async def test_surfaces_do_not_accept_each_others_tokens(client_for: ClientFor) -> None:
    customer = await client_for("c@example.com")
    admin_as_customer_token = await client_for("a@example.com", PlatformRole.platform_admin)
    admin_token = await client_for(
        "a2@example.com", PlatformRole.platform_admin, audience=sec.AUDIENCE_ADMIN
    )
    assert (await customer.get("/admin/stats")).status_code == 401  # customer token, admin route
    assert (
        await admin_as_customer_token.get("/admin/stats")
    ).status_code == 401  # right person, wrong audience
    assert (await admin_token.get("/admin/stats")).status_code == 200
    assert (
        await admin_token.get("/projects")
    ).status_code == 401  # admin token on the customer surface
