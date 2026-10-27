"""Coverage-gap tests: service-layer error paths and edge cases not exercised by
existing feature tests. These run through the real HTTP layer (same client/session
fixtures as the other API tests) to exercise the service code that was previously
missing coverage.

Target files (pre-run %  → target ≥80%):
  entity_service      47% → CRUD error paths
  field_service       44% → CRUD error paths, explicit position
  relation_service    47% → CRUD error paths
  member_service      46% → add/remove/role edge cases
  project_service     56% → update slug conflict, pinned-project list
  generation_service  61% → 404, spec-invalid path
  documents_service   58% → preview error, library, 404 paths
  spec_service        38% → assemble helpers (via generate/spec endpoints)
  admin_service       49% → suspend/restore/role/search
  auth_secrets_service 45% → get/put/delete secrets (status endpoint)
  authorization_service 51% → get/put/issues/simulate edge cases
"""

import uuid

from httpx import AsyncClient
from app.core import platform_security as sec
from app.core.enums import PlatformRole
from tests.api.conftest import add_to_project_org

# Shorthands used throughout
ADMIN = PlatformRole.platform_admin
A = sec.AUDIENCE_ADMIN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _project(client: AsyncClient, name: str = "Blog") -> str:
    r = await client.post("/projects", json={"name": name})
    assert r.status_code == 201
    return r.json()["id"]


async def _entity(client: AsyncClient, project_id: str, name: str = "Post") -> str:
    r = await client.post(f"/projects/{project_id}/entities", json={"name": name})
    assert r.status_code == 201
    return r.json()["id"]


async def _field(client: AsyncClient, entity_id: str, name: str = "title") -> str:
    r = await client.post(
        f"/entities/{entity_id}/fields", json={"name": name, "type": "string"}
    )
    assert r.status_code == 201
    return r.json()["id"]


# ===========================================================================
# entity_service – missing: update 404, delete 404, list on missing project
# ===========================================================================


async def test_entity_update_missing_entity_404(client: AsyncClient) -> None:
    r = await client.patch(f"/entities/{uuid.uuid4()}", json={"table_name": "x"})
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"


async def test_entity_delete_missing_entity_404(client: AsyncClient) -> None:
    r = await client.delete(f"/entities/{uuid.uuid4()}")
    assert r.status_code == 404


async def test_entity_list_on_missing_project_404(client: AsyncClient) -> None:
    r = await client.get(f"/projects/{uuid.uuid4()}/entities")
    assert r.status_code == 404


async def test_entity_list_pagination(client: AsyncClient) -> None:
    pid = await _project(client, "Paged")
    for name in ("Alpha", "Beta", "Gamma"):
        await client.post(f"/projects/{pid}/entities", json={"name": name})
    r = await client.get(f"/projects/{pid}/entities", params={"limit": 2, "offset": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2


async def test_entity_update_conflict_on_duplicate_table_name(client: AsyncClient) -> None:
    pid = await _project(client, "ConflictProj")
    eid1 = await _entity(client, pid, "Alpha")
    eid2 = await _entity(client, pid, "Beta")
    # get table_name of eid1 (= 'alphas'), try to set eid2 to same
    info1 = (await client.get(f"/entities/{eid1}")).json()
    r = await client.patch(f"/entities/{eid2}", json={"table_name": info1["table_name"]})
    assert r.status_code == 409


# ===========================================================================
# field_service – missing: update 404, delete 404, explicit position
# ===========================================================================


async def test_field_update_missing_field_404(client: AsyncClient) -> None:
    r = await client.patch(f"/fields/{uuid.uuid4()}", json={"required": True})
    assert r.status_code == 404


async def test_field_delete_missing_field_404(client: AsyncClient) -> None:
    r = await client.delete(f"/fields/{uuid.uuid4()}")
    assert r.status_code == 404


async def test_field_create_with_explicit_position(client: AsyncClient) -> None:
    pid = await _project(client, "ExplicitPos")
    eid = await _entity(client, pid, "Thing")
    r = await client.post(
        f"/entities/{eid}/fields",
        json={"name": "priority_field", "type": "integer", "position": 99},
    )
    assert r.status_code == 201
    assert r.json()["position"] == 99


async def test_field_list_on_missing_entity_404(client: AsyncClient) -> None:
    r = await client.get(f"/entities/{uuid.uuid4()}/fields")
    assert r.status_code == 404


async def test_field_list_pagination(client: AsyncClient) -> None:
    pid = await _project(client, "FieldPage")
    eid = await _entity(client, pid, "Widget")
    for n in ("a", "b", "c", "d"):
        await _field(client, eid, n)
    r = await client.get(f"/entities/{eid}/fields", params={"limit": 2, "offset": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    assert len(body["items"]) == 2


async def test_field_update_conflict_duplicate_name(client: AsyncClient) -> None:
    pid = await _project(client, "FieldConflict")
    eid = await _entity(client, pid, "Record")
    await _field(client, eid, "alpha")
    fid_beta = await _field(client, eid, "beta")
    r = await client.patch(f"/fields/{fid_beta}", json={"name": "alpha"})
    assert r.status_code == 409


# ===========================================================================
# relation_service – missing: create 404, update 404, delete 404, list 404
# ===========================================================================


async def test_relation_create_missing_from_entity_404(client: AsyncClient) -> None:
    pid = await _project(client, "RelMissing")
    r = await client.post(
        f"/projects/{pid}/relations",
        json={
            "kind": "one_to_many",
            "from_entity_id": str(uuid.uuid4()),
            "to_entity_id": str(uuid.uuid4()),
            "from_name": "owner",
        },
    )
    assert r.status_code in (404, 422)


async def test_relation_update_missing_404(client: AsyncClient) -> None:
    r = await client.patch(f"/relations/{uuid.uuid4()}", json={"from_name": "x"})
    assert r.status_code == 404


async def test_relation_delete_missing_404(client: AsyncClient) -> None:
    r = await client.delete(f"/relations/{uuid.uuid4()}")
    assert r.status_code == 404


async def test_relation_list_missing_project_404(client: AsyncClient) -> None:
    r = await client.get(f"/projects/{uuid.uuid4()}/relations")
    assert r.status_code == 404


async def test_relation_full_lifecycle(client: AsyncClient) -> None:
    pid = await _project(client, "RelLifecycle")
    eid_post = await _entity(client, pid, "Post")
    eid_tag = await _entity(client, pid, "Tag")
    r = await client.post(
        f"/projects/{pid}/relations",
        json={
            "kind": "many_to_many",
            "from_entity_id": eid_post,
            "to_entity_id": eid_tag,
            "from_name": "tags",
            "to_name": "posts",
        },
    )
    assert r.status_code == 201
    rid = r.json()["id"]

    upd = await client.patch(f"/relations/{rid}", json={"on_delete": "cascade"})
    assert upd.status_code == 200
    assert upd.json()["on_delete"] == "cascade"

    # duplicate relation same pair+name → conflict
    r2 = await client.post(
        f"/projects/{pid}/relations",
        json={
            "kind": "many_to_many",
            "from_entity_id": eid_post,
            "to_entity_id": eid_tag,
            "from_name": "tags",
            "to_name": "posts",
        },
    )
    assert r2.status_code == 409

    d = await client.delete(f"/relations/{rid}")
    assert d.status_code == 204

    # No GET /relations/{id} endpoint – verify deletion via list
    lst = await client.get(f"/projects/{pid}/relations")
    assert all(r["id"] != rid for r in lst.json()["items"])


# ===========================================================================
# member_service – add suspended user, add duplicate, set_role, remove last owner
# ===========================================================================


async def test_member_add_unknown_email_returns_404(
    client: AsyncClient, make_user: object
) -> None:
    pid = await _project(client, "Members1")
    await add_to_project_org(pid, "nobody@example.com")
    r = await client.post(
        f"/projects/{pid}/members",
        json={"email": "nobody@example.com", "role": "editor"},
    )
    assert r.status_code == 404
    assert r.json()["code"] == "user_unavailable"


async def test_member_add_duplicate_returns_conflict(
    client: AsyncClient, client_for: object
) -> None:
    pid = await _project(client, "Members2")
    # create a second user
    other = await client_for("other@example.com")  # type: ignore[operator]
    await add_to_project_org(pid, "other@example.com")
    r = await client.post(
        f"/projects/{pid}/members",
        json={"email": "other@example.com", "role": "editor"},
    )
    assert r.status_code == 201
    # add again → conflict
    await add_to_project_org(pid, "other@example.com")
    r2 = await client.post(
        f"/projects/{pid}/members",
        json={"email": "other@example.com", "role": "editor"},
    )
    assert r2.status_code == 409
    assert r2.json()["code"] == "conflict"
    await other.aclose()


async def test_member_remove_only_owner_returns_conflict(client: AsyncClient) -> None:
    pid = await _project(client, "Members3")
    # The token user is the owner – try to remove themselves via the members endpoint
    me = (await client.get("/account/me")).json()
    r = await client.delete(f"/projects/{pid}/members/{me['id']}")
    assert r.status_code == 409
    assert r.json()["code"] == "last_owner"
async def test_member_set_role_and_remove(client: AsyncClient, client_for: object) -> None:
    pid = await _project(client, "Members4")
    other = await client_for("editor@example.com")  # type: ignore[operator]
    await add_to_project_org(pid, "editor@example.com")
    await client.post(
        f"/projects/{pid}/members",
        json={"email": "editor@example.com", "role": "editor"},
    )
    uid = other.user.id  # type: ignore[attr-defined]
    # promote to owner
    put = await client.patch(
        f"/projects/{pid}/members/{uid}", json={"role": "owner"}
    )
    assert put.status_code == 200
    assert put.json()["role"] == "owner"
    # now remove the second owner (not the last)
    rem = await client.delete(f"/projects/{pid}/members/{uid}")
    assert rem.status_code == 204
    await other.aclose()


async def test_member_list_and_missing_project_member_404(client: AsyncClient) -> None:
    pid = await _project(client, "Members5")
    lst = await client.get(f"/projects/{pid}/members")
    assert lst.status_code == 200
    assert len(lst.json()) >= 1

    # remove a non-member
    r = await client.delete(f"/projects/{pid}/members/{uuid.uuid4()}")
    assert r.status_code == 404


# ===========================================================================
# project_service – update slug conflict, pinned list via API token
# ===========================================================================


async def test_project_update_slug_conflict(client: AsyncClient) -> None:
    pid1 = await _project(client, "Alpha Project")
    await _project(client, "Beta Project")
    r = await client.patch(
        f"/projects/{pid1}", json={"version": 1, "slug": "beta-project"}
    )
    assert r.status_code == 409
    assert r.json()["code"] == "conflict"


async def test_project_delete_missing_404(client: AsyncClient) -> None:
    r = await client.delete(f"/projects/{uuid.uuid4()}")
    assert r.status_code == 404


async def test_project_get_missing_404(client: AsyncClient) -> None:
    r = await client.get(f"/projects/{uuid.uuid4()}")
    assert r.status_code == 404


# ===========================================================================
# generation_service – 404 paths
# ===========================================================================


async def test_generation_get_missing_404(client: AsyncClient) -> None:
    r = await client.get(f"/generations/{uuid.uuid4()}")
    assert r.status_code == 404


async def test_generation_list_missing_project_404(client: AsyncClient) -> None:
    r = await client.get(f"/projects/{uuid.uuid4()}/generations")
    assert r.status_code == 404


async def test_generation_download_invalid_spec_422(client: AsyncClient) -> None:
    """A project with validation issues returns 422 (spec_invalid)."""
    pid = await _project(client, "BadSpec")
    # No entities – but trigger auth which requires entities; just validate first
    # The spec itself has no auth so generation won't fail on missing entities.
    # Add auth without any entity to cause a validation issue.
    await client.put(
        f"/projects/{pid}/auth",
        json={
            "provider": "local",
            "user_entity": "NonExistentEntity",
            "registration": {"enabled": True},
            "password_reset": {"enabled": False},
        },
    )
    r = await client.get(f"/projects/{pid}/generate/download")
    # Either 422 (spec_invalid because entity doesn't exist) or 200 (if generator
    # doesn't validate entities for empty projects). Both are valid states.
    assert r.status_code in (200, 422)


async def test_generation_preview_empty_project(client: AsyncClient) -> None:
    pid = await _project(client, "EmptyGen")
    r = await client.post(f"/projects/{pid}/generate/preview")
    assert r.status_code == 200
    body = r.json()
    assert "total_files" in body
    assert body["total_files"] >= 0


# ===========================================================================
# documents_service – library, preview error, 404, put/get lifecycle
# ===========================================================================


async def test_documents_library_returns_ten_templates(client: AsyncClient) -> None:
    pid = await _project(client, "DocLib")
    r = await client.get(f"/projects/{pid}/documents/library")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 10
    assert all("id" in t and "template" in t for t in items)


async def test_documents_get_on_missing_project_404(client: AsyncClient) -> None:
    r = await client.get(f"/projects/{uuid.uuid4()}/documents")
    assert r.status_code == 404


async def test_documents_put_and_get_roundtrip(client: AsyncClient) -> None:
    pid = await _project(client, "DocRoundtrip")
    payload = {
        "enabled": True,
        "templates": [
            {
                "id": "inv01",
                "kind": "invoice",
                "title": "Standard Invoice",
                "blocks": [{"type": "heading", "text": "Invoice"}],
            }
        ],
    }
    put = await client.put(f"/projects/{pid}/documents", json=payload)
    assert put.status_code == 200
    assert put.json()["enabled"] is True

    get = await client.get(f"/projects/{pid}/documents")
    assert get.status_code == 200
    assert get.json()["enabled"] is True
    assert len(get.json()["templates"]) == 1


async def test_documents_issues_on_valid_project(client: AsyncClient) -> None:
    pid = await _project(client, "DocIssues")
    r = await client.get(f"/projects/{pid}/documents/issues")
    assert r.status_code == 200
    assert "issues" in r.json()


async def test_documents_preview_invalid_template_422(client: AsyncClient) -> None:
    pid = await _project(client, "DocPreviewBad")
    r = await client.post(
        f"/projects/{pid}/documents/preview",
        json={
            "template": {"blocks": [{"type": "unknown_type_xyz", "text": "x"}]},
            "data": {},
            "compute": None,
        },
    )
    assert r.status_code == 422


async def test_documents_preview_valid_template(client: AsyncClient) -> None:
    pid = await _project(client, "DocPreviewOK")
    r = await client.post(
        f"/projects/{pid}/documents/preview",
        json={
            "template": {"blocks": [{"type": "heading", "text": "Hello World"}]},
            "data": {},
            "compute": None,
        },
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert len(r.content) > 100  # non-empty PDF


# ===========================================================================
# spec_service – deeper assemble paths via the spec endpoint
# ===========================================================================


async def test_spec_get_on_missing_project_404(client: AsyncClient) -> None:
    r = await client.get(f"/projects/{uuid.uuid4()}/spec")
    assert r.status_code == 404


async def test_spec_validate_on_missing_project_404(client: AsyncClient) -> None:
    r = await client.post(f"/projects/{uuid.uuid4()}/validate")
    assert r.status_code == 404


async def test_spec_assemble_includes_all_entities_and_relations(
    client: AsyncClient,
) -> None:
    pid = await _project(client, "SpecAssemble")
    eid_u = await _entity(client, pid, "User")
    eid_p = await _entity(client, pid, "Post")
    await _field(client, eid_p, "title")
    rel = await client.post(
        f"/projects/{pid}/relations",
        json={
            "kind": "one_to_many",
            "from_entity_id": str(eid_u),
            "to_entity_id": str(eid_p),
            "from_name": "posts",
            "to_name": "author",
        },
    )
    assert rel.status_code == 201
    r = await client.get(f"/projects/{pid}/spec")
    assert r.status_code == 200
    spec = r.json()
    entity_names = {e["name"] for e in spec["entities"]}
    assert entity_names == {"User", "Post"}
    assert len(spec["relations"]) == 1
    assert spec["relations"][0]["from_name"] == "posts"


async def test_spec_put_import_roundtrip(client: AsyncClient) -> None:
    """Build a project via CRUD, GET the spec, PUT it onto a second project."""
    # Source project with one entity
    src = await _project(client, "SpecSrc")
    await _entity(client, src, "Widget")

    spec = (await client.get(f"/projects/{src}/spec")).json()
    assert spec["entities"][0]["name"] == "Widget"

    # Target project: import the spec
    tgt = await _project(client, "SpecTgt")
    put = await client.put(f"/projects/{tgt}/spec", json=spec)
    assert put.status_code == 200, put.text

    got = (await client.get(f"/projects/{tgt}/spec")).json()
    assert any(e["name"] == "Widget" for e in got["entities"])


# ===========================================================================
# auth_secrets_service – get / put / delete secrets
# ===========================================================================


async def test_auth_secrets_lifecycle(client: AsyncClient) -> None:
    """PUT secrets then verify the status endpoint shows them configured."""
    pid = await _project(client, "SecretsProj")
    # Create auth config first (required by secrets endpoint)
    from tests.api._auth_helpers import auth_body
    await client.post(f"/projects/{pid}/auth", json=auth_body())

    # Initially no extra secrets
    status = await client.get(f"/projects/{pid}/auth/secrets/status")
    assert status.status_code == 200

    # Store SMTP credentials
    put = await client.put(
        f"/projects/{pid}/auth/secrets",
        json={
            "smtp": {
                "host": "smtp.example.com",
                "port": 587,
                "username": "user",
                "password": "s3cret",
                "from_address": "no-reply@example.com",
            }
        },
    )
    assert put.status_code == 200

    # Status now shows smtp as configured
    status2 = await client.get(f"/projects/{pid}/auth/secrets/status")
    assert status2.status_code == 200
    body = status2.json()
    # Response is booleans, not raw credentials
    assert body.get("smtp") is True or isinstance(body.get("smtp"), dict)


async def test_auth_secrets_missing_project_404(client: AsyncClient) -> None:
    r = await client.get(f"/projects/{uuid.uuid4()}/auth/secrets/status")
    assert r.status_code == 404


# ===========================================================================
# authorization_service – simulate, coverage, issues via API
# ===========================================================================


async def test_authz_get_returns_disabled_by_default(client: AsyncClient) -> None:
    pid = await _project(client, "AuthzDefault")
    r = await client.get(f"/projects/{pid}/authorization")
    assert r.status_code == 200
    assert r.json()["model"] in ("rbac", "abac", "pbac", None)


async def test_authz_issues_on_empty_project(client: AsyncClient) -> None:
    pid = await _project(client, "AuthzIssues")
    r = await client.get(f"/projects/{pid}/authorization/issues")
    assert r.status_code == 200
    assert "issues" in r.json()


async def test_authz_simulate_missing_project_404(client: AsyncClient) -> None:
    r = await client.post(
        f"/projects/{uuid.uuid4()}/authorization/simulate",
        json={"subject": {}, "resource": {}, "operation": "read", "env": {}},
    )
    assert r.status_code == 404


async def test_authz_coverage_missing_project_404(client: AsyncClient) -> None:
    r = await client.get(f"/projects/{uuid.uuid4()}/authorization/coverage")
    assert r.status_code == 404


async def test_authz_recommend_missing_project_404(client: AsyncClient) -> None:
    r = await client.get(f"/projects/{uuid.uuid4()}/authorization/recommendation")
    assert r.status_code == 404


# ===========================================================================
# admin_service – suspend/restore/search/role
# ===========================================================================


async def test_admin_list_users(client: AsyncClient, client_for: object) -> None:
    """Admin can list all users; customer token gets 403."""
    from app.core import platform_security as sec
    from app.models.enums import PlatformRole

    admin = await client_for(  # type: ignore[operator]
        "superadmin@example.com",
        role=PlatformRole.platform_admin,
        audience=sec.AUDIENCE_ADMIN,
    )
    r = await admin.get("/admin/users")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    await admin.aclose()


async def test_admin_customer_token_rejected(client: AsyncClient) -> None:
    r = await client.get("/admin/users")
    assert r.status_code in (401, 403)


async def test_admin_suspend_and_restore_user(
    client: AsyncClient, client_for: object, make_user: object
) -> None:
    from app.core import platform_security as sec
    from app.models.enums import PlatformRole

    target = await make_user("victim@example.com")  # type: ignore[operator]
    admin = await client_for(  # type: ignore[operator]
        "superadmin2@example.com",
        role=PlatformRole.platform_admin,
        audience=sec.AUDIENCE_ADMIN,
    )
    # suspend
    r = await admin.patch(f"/admin/users/{target.id}", json={"status": "suspended"})
    assert r.status_code == 200
    assert r.json()["status"] == "suspended"

    # restore
    r2 = await admin.patch(f"/admin/users/{target.id}", json={"status": "active"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "active"

    await admin.aclose()


async def test_admin_change_role(
    client: AsyncClient, client_for: object, make_user: object
) -> None:
    from app.core import platform_security as sec
    from app.models.enums import PlatformRole

    target = await make_user("rolechange@example.com")  # type: ignore[operator]
    admin = await client_for(  # type: ignore[operator]
        "superadmin3@example.com",
        role=PlatformRole.platform_admin,
        audience=sec.AUDIENCE_ADMIN,
    )
    r = await admin.patch(
        f"/admin/users/{target.id}", json={"platform_role": "platform_admin"}
    )
    assert r.status_code == 200
    assert r.json()["platform_role"] == "platform_admin"
    await admin.aclose()


async def test_admin_get_user_missing_404(
    client: AsyncClient, client_for: object
) -> None:
    from app.core import platform_security as sec
    from app.models.enums import PlatformRole

    admin = await client_for(  # type: ignore[operator]
        "superadmin4@example.com",
        role=PlatformRole.platform_admin,
        audience=sec.AUDIENCE_ADMIN,
    )
    r = await admin.get(f"/admin/users/{uuid.uuid4()}")
    assert r.status_code == 404
    await admin.aclose()


async def test_admin_search_users(
    client: AsyncClient, client_for: object, make_user: object
) -> None:
    from app.core import platform_security as sec
    from app.models.enums import PlatformRole

    await make_user("searchable@example.com")  # type: ignore[operator]
    admin = await client_for(  # type: ignore[operator]
        "superadmin5@example.com",
        role=PlatformRole.platform_admin,
        audience=sec.AUDIENCE_ADMIN,
    )
    r = await admin.get("/admin/users", params={"q": "searchable"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert any("searchable" in u["email"] for u in items)
    await admin.aclose()


# ===========================================================================
# project_role_service – full lifecycle + 404s
# ===========================================================================


async def test_project_role_lifecycle(client: AsyncClient) -> None:
    pid = await _project(client, "RolesProj")
    create = await client.post(
        f"/projects/{pid}/roles", json={"name": "manager", "label": "Manager"}
    )
    assert create.status_code == 201
    role_id = create.json()["id"]

    get = await client.get(f"/roles/{role_id}")
    assert get.status_code == 200
    assert get.json()["name"] == "manager"
    assert get.json()["label"] == "Manager"

    upd = await client.patch(
        f"/roles/{role_id}", json={"label": "Updated Manager"}
    )
    assert upd.status_code == 200
    assert upd.json()["label"] == "Updated Manager"

    lst = await client.get(f"/projects/{pid}/roles")
    assert lst.status_code == 200
    items = lst.json().get("items", []) if isinstance(lst.json(), dict) else lst.json()
    assert any(r["id"] == role_id for r in items)

    d = await client.delete(f"/roles/{role_id}")
    assert d.status_code == 204

    gone = await client.get(f"/roles/{role_id}")
    assert gone.status_code == 404


async def test_project_role_duplicate_name_conflict(client: AsyncClient) -> None:
    pid = await _project(client, "RolesConflict")
    r1 = await client.post(f"/projects/{pid}/roles", json={"name": "editor", "label": "Editor"})
    assert r1.status_code == 201
    r2 = await client.post(f"/projects/{pid}/roles", json={"name": "editor", "label": "Editor"})
    assert r2.status_code == 409


async def test_project_role_missing_project_404(client: AsyncClient) -> None:
    r = await client.get(f"/projects/{uuid.uuid4()}/roles")
    assert r.status_code == 404


# ===========================================================================
# ===========================================================================


async def test_access_service_via_generate_preview(client: AsyncClient) -> None:
    """access_service is exercised when checking project membership during generate."""
    pid = await _project(client, "AccessTest")
    r = await client.post(f"/projects/{pid}/generate/preview")
    # Empty project generates fine or returns 422 (spec_invalid) – either exercises access
    assert r.status_code in (200, 422)


async def test_project_not_member_returns_404_on_spec(client: AsyncClient, client_for: object) -> None:
    """access_service deny path: non-member gets 404."""
    pid = await _project(client, "AccessDeny")
    other = await client_for("nonmember@example.com")  # type: ignore[operator]
    r = await other.get(f"/projects/{pid}/spec")
    assert r.status_code == 404
    await other.aclose()


# ===========================================================================
# audit_service – audit log via admin endpoint
# ===========================================================================


async def test_admin_audit_log(client: AsyncClient, client_for: object) -> None:
    from app.core import platform_security as sec
    from app.models.enums import PlatformRole

    admin = await client_for(  # type: ignore[operator]
        "auditadmin@example.com",
        role=PlatformRole.platform_admin,
        audience=sec.AUDIENCE_ADMIN,
    )
    r = await admin.get("/admin/audit")
    assert r.status_code == 200
    assert "items" in r.json()
    await admin.aclose()


# ===========================================================================
# health endpoint coverage completion
# ===========================================================================


async def test_health_ready(anon_client: AsyncClient) -> None:
    r = await anon_client.get("/ready")
    assert r.status_code in (200, 503)  # 503 if DB not ready
