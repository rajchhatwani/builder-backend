"""Auth through the whole builder: configure over the API, assemble the spec, import it into
another project, validate, and generate a zip that contains the auth module."""

import io
import zipfile
from typing import Any

from httpx import AsyncClient

from tests.api._auth_helpers import SMTP, make_auth, make_entity, make_project, make_role

SECRETS = {
    "smtp": {"username": "ZZmailerZZ", "password": "ZZsmtp-passZZ"},
    "twilio": {"account_sid": "ZZACsidZZ", "auth_token": "ZZtwilio-tokenZZ"},
}
SECRET_MARKERS = ("ZZmailerZZ", "ZZsmtp-passZZ", "ZZACsidZZ", "ZZtwilio-tokenZZ")


async def build_shop(client: AsyncClient) -> str:
    """A shop with email + SMS auth, roles, custom fields and stored credentials."""
    project_id = await make_project(client, "Shop")
    item = await make_entity(client, project_id, "Item")
    await client.post(
        f"/entities/{item}/fields",
        json={"name": "title", "type": "string", "required": True, "max_length": 100},
    )
    await make_auth(
        client,
        project_id,
        sms_otp_enabled=True,
        sms_provider="twilio",
        sms_config={"from_number": "+14155550100"},
        app_name="Shop",
        deletion_mode="hard",
        login_rate_limit="3/minute",
    )
    await make_role(client, project_id, "admin", position=0)
    await make_role(client, project_id, "staff", inherits_from="admin", position=1)
    await make_role(client, project_id, "customer", is_default=True, position=2)
    for payload in (
        {
            "name": "full_name",
            "label": "Full name",
            "type": "string",
            "required": True,
            "max_length": 80,
        },
        {"name": "age", "label": "Age", "type": "integer", "min_value": 13, "max_value": 120},
        {
            "name": "plan",
            "label": "Plan",
            "type": "enum",
            "enum_values": ["free", "pro"],
            "default_value": "free",
        },
    ):
        created = await client.post(f"/projects/{project_id}/auth/custom-fields", json=payload)
        assert created.status_code == 201, created.text
    stored = await client.put(f"/projects/{project_id}/auth/secrets", json=SECRETS)
    assert stored.status_code == 200, stored.text
    return project_id


async def test_spec_carries_the_whole_auth_block(client: AsyncClient) -> None:
    project_id = await build_shop(client)

    spec = (await client.get(f"/projects/{project_id}/spec")).json()

    auth = spec["auth"]
    assert auth["enabled"] is True
    assert auth["deletion_mode"] == "hard"
    assert auth["login_rate_limit"] == "3/minute"
    assert auth["smtp"] == SMTP
    assert auth["sms_provider"] == "twilio"
    assert auth["sms"] == {"from_number": "+14155550100"}
    assert auth["password_reset"] == {
        "email_magic_link": True,
        "sms_otp": True,
        "otp_ttl_minutes": 10,
    }
    assert [r["name"] for r in auth["roles"]] == ["admin", "staff", "customer"]
    assert auth["roles"][1]["inherits_from"] == "admin"
    assert [f["name"] for f in auth["registration"]["custom_fields"]] == [
        "full_name",
        "age",
        "plan",
    ]
    assert auth["permissions"] == []


async def test_credentials_never_appear_in_the_spec(client: AsyncClient) -> None:
    project_id = await build_shop(client)

    response = await client.get(f"/projects/{project_id}/spec")

    assert "secrets" not in response.json()["auth"]
    for marker in SECRET_MARKERS:
        assert marker not in response.text


async def test_the_shop_validates_clean(client: AsyncClient) -> None:
    project_id = await build_shop(client)

    response = await client.post(f"/projects/{project_id}/validate")

    assert response.json() == {"valid": True, "issues": []}


async def test_preview_and_download_contain_the_auth_module(client: AsyncClient) -> None:
    project_id = await build_shop(client)

    preview = (await client.post(f"/projects/{project_id}/generate/preview")).json()
    paths = {f["path"] for f in preview["files"]}
    assert {
        "app/auth/router.py",
        "app/auth/service.py",
        "app/auth/security.py",
        "app/auth/delivery.py",
        "app/auth/models.py",
        "alembic/versions/0002_auth.py",
        "tests/test_auth.py",
    } <= paths

    download = await client.get(f"/projects/{project_id}/generate/download")
    assert download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        names = archive.namelist()
        assert "shop/app/auth/router.py" in names
        for name in names:
            text = archive.read(name).decode("utf-8", errors="replace")
            for marker in SECRET_MARKERS:
                assert marker not in text, f"{marker} leaked into {name}"
        env_example = archive.read("shop/.env.example").decode()
        assert "AUTH_JWT_SECRET=" in env_example
        assert "TWILIO_AUTH_TOKEN=" in env_example
        models = archive.read("shop/app/auth/models.py").decode()
        assert "full_name" in models and "plan" in models


async def test_generation_history_snapshot_has_no_credentials(client: AsyncClient) -> None:
    project_id = await build_shop(client)
    await client.get(f"/projects/{project_id}/generate/download")

    history = await client.get(f"/projects/{project_id}/generations")

    assert history.json()["total"] == 1
    for marker in SECRET_MARKERS:
        assert marker not in history.text


async def test_toggling_auth_off_removes_the_module(client: AsyncClient) -> None:
    project_id = await build_shop(client)
    await client.patch(f"/projects/{project_id}/auth", json={"enabled": False})

    preview = (await client.post(f"/projects/{project_id}/generate/preview")).json()

    assert not any(f["path"].startswith("app/auth/") for f in preview["files"])


async def test_incomplete_auth_blocks_generation_with_clear_issues(client: AsyncClient) -> None:
    project_id = await make_project(client, "Half")
    await make_entity(client, project_id, "Item")
    # Magic link and email verification are on by default but no app_url is set.
    created = await client.post(f"/projects/{project_id}/auth", json={"smtp_config": SMTP})
    assert created.status_code == 201

    validation = (await client.post(f"/projects/{project_id}/validate")).json()
    generate = await client.get(f"/projects/{project_id}/generate/download")

    assert validation["valid"] is False
    assert [(i["path"], i["code"]) for i in validation["issues"]] == [("auth.app_url", "required")]
    assert generate.status_code == 422
    assert generate.json()["code"] == "spec_invalid"


async def test_permissions_are_generated_into_the_routers(client: AsyncClient) -> None:
    project_id = await build_shop(client)
    entity = (await client.get(f"/projects/{project_id}/entities")).json()["items"][0]["id"]
    await client.post(
        f"/projects/{project_id}/permissions",
        json={
            "permissions": [
                {"entity_id": entity, "operation": "list", "roles": ["admin"], "row_rule": "owner"},
                {"entity_id": entity, "operation": "create", "roles": ["customer"]},
            ]
        },
    )

    validation = (await client.post(f"/projects/{project_id}/validate")).json()
    download = await client.get(f"/projects/{project_id}/generate/download")

    assert validation == {"valid": True, "issues": []}
    assert download.status_code == 200
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        router = archive.read("shop/app/routers/items.py").decode()
        assert 'access_dependency(roles=("admin",), owner=True, authenticate=True)' in router
        assert "tests/test_access.py" in "".join(archive.namelist())
        migration = archive.read("shop/alembic/versions/0002_auth.py").decode()
        assert "created_by_id" in migration


async def test_the_tenant_rule_needs_multi_tenancy_to_generate(client: AsyncClient) -> None:
    project_id = await build_shop(client)
    entity = (await client.get(f"/projects/{project_id}/entities")).json()["items"][0]["id"]
    await client.post(
        f"/projects/{project_id}/permissions",
        json={
            "permissions": [
                {"entity_id": entity, "operation": "list", "roles": ["admin"], "row_rule": "tenant"}
            ]
        },
    )

    validation = (await client.post(f"/projects/{project_id}/validate")).json()

    assert ("auth.permissions[0].row_rule", "invalid_value") in [
        (i["path"], i["code"]) for i in validation["issues"]
    ]
    assert (await client.get(f"/projects/{project_id}/generate/download")).status_code == 422


# --- importing a spec ----------------------------------------------------------------------


async def _copy_spec_into_new_project(client: AsyncClient, source_id: str) -> tuple[str, Any]:
    spec = (await client.get(f"/projects/{source_id}/spec")).json()
    target = await client.post("/projects", json={"name": "Copy", "slug": "copy"})
    target_id: str = target.json()["id"]
    put = await client.put(f"/projects/{target_id}/spec", json=spec)
    assert put.status_code == 200, put.text
    return target_id, spec


async def test_spec_round_trip_keeps_the_auth_block(client: AsyncClient) -> None:
    source_id = await build_shop(client)

    target_id, spec = await _copy_spec_into_new_project(client, source_id)

    round_tripped = (await client.get(f"/projects/{target_id}/spec")).json()
    assert round_tripped["auth"] == spec["auth"]
    assert (await client.post(f"/projects/{target_id}/validate")).json()["valid"] is True
    # The imported project generates the same auth files as the original.
    original = {
        f["path"]: f["size"]
        for f in (await client.post(f"/projects/{source_id}/generate/preview")).json()["files"]
    }
    copied = {
        f["path"]: f["size"]
        for f in (await client.post(f"/projects/{target_id}/generate/preview")).json()["files"]
    }
    assert {p for p in original if p.startswith("app/auth/")} == {
        p for p in copied if p.startswith("app/auth/")
    }


async def test_import_does_not_copy_credentials(client: AsyncClient) -> None:
    source_id = await build_shop(client)

    target_id, _ = await _copy_spec_into_new_project(client, source_id)

    status = (await client.get(f"/projects/{target_id}/auth/secrets/status")).json()
    assert status["smtp"]["configured"] is False
    assert status["sms"]["configured"] is False


async def test_import_replaces_the_existing_auth_block(client: AsyncClient) -> None:
    project_id = await build_shop(client)
    spec = (await client.get(f"/projects/{project_id}/spec")).json()
    spec["auth"]["roles"] = [{"name": "owner", "label": "Owner", "is_default": True}]
    spec["auth"]["registration"]["custom_fields"] = []
    spec["auth"]["access_token_ttl_minutes"] = 45

    put = await client.put(f"/projects/{project_id}/spec", json=spec)

    assert put.status_code == 200, put.text
    roles = (await client.get(f"/projects/{project_id}/roles")).json()
    assert [r["name"] for r in roles["items"]] == ["owner"]
    assert (await client.get(f"/projects/{project_id}/auth/custom-fields")).json()["total"] == 0
    assert (await client.get(f"/projects/{project_id}/auth")).json()[
        "access_token_ttl_minutes"
    ] == 45


async def test_import_without_auth_leaves_auth_alone_and_keeps_permissions(
    client: AsyncClient,
) -> None:
    project_id = await build_shop(client)
    entity = (await client.get(f"/projects/{project_id}/entities")).json()["items"][0]["id"]
    await client.post(
        f"/projects/{project_id}/permissions",
        json={"permissions": [{"entity_id": entity, "operation": "list", "roles": ["admin"]}]},
    )
    spec = (await client.get(f"/projects/{project_id}/spec")).json()
    del spec["auth"]

    put = await client.put(f"/projects/{project_id}/spec", json=spec)

    assert put.status_code == 200, put.text
    assert (await client.get(f"/projects/{project_id}/auth")).status_code == 200
    assert (await client.get(f"/projects/{project_id}/roles")).json()["total"] == 3
    permissions = (await client.get(f"/projects/{project_id}/permissions")).json()
    assert permissions["total"] == 1
    new_entity = (await client.get(f"/projects/{project_id}/entities")).json()["items"][0]["id"]
    assert new_entity != entity  # entities were re-created...
    assert permissions["items"][0]["entity_id"] == new_entity  # ...and the permission followed


async def test_import_drops_permissions_for_entities_that_no_longer_exist(
    client: AsyncClient,
) -> None:
    project_id = await build_shop(client)
    entity = (await client.get(f"/projects/{project_id}/entities")).json()["items"][0]["id"]
    await client.post(
        f"/projects/{project_id}/permissions",
        json={"permissions": [{"entity_id": entity, "operation": "list", "roles": ["admin"]}]},
    )
    spec = (await client.get(f"/projects/{project_id}/spec")).json()
    del spec["auth"]
    spec["entities"][0].update(name="Product", table_name="products", plural_path="products")

    put = await client.put(f"/projects/{project_id}/spec", json=spec)

    assert put.status_code == 200, put.text
    assert (await client.get(f"/projects/{project_id}/permissions")).json()["total"] == 0


async def test_invalid_auth_in_an_imported_spec_changes_nothing(client: AsyncClient) -> None:
    project_id = await build_shop(client)
    spec = (await client.get(f"/projects/{project_id}/spec")).json()
    spec["auth"]["roles"] = [{"name": "Bad Name", "label": "x"}]
    spec["auth"]["multi_tenant"] = True
    spec["auth"]["registration"]["invite_only"] = True  # no way to create the first tenant

    put = await client.put(f"/projects/{project_id}/spec", json=spec)

    assert put.status_code == 422
    assert put.json()["code"] == "spec_invalid"
    assert {i["path"] for i in put.json()["details"]} >= {
        "auth.roles[0].name",
        "auth.multi_tenant",
    }
    roles = (await client.get(f"/projects/{project_id}/roles")).json()
    assert [r["name"] for r in roles["items"]] == ["admin", "staff", "customer"]


async def test_disabled_auth_with_a_bad_enum_is_rejected_not_a_server_error(
    client: AsyncClient,
) -> None:
    project_id = await make_project(client)
    spec = (await client.get(f"/projects/{project_id}/spec")).json()
    spec["auth"] = {"enabled": False, "token_store": "memcached", "deletion_mode": "shred"}

    put = await client.put(f"/projects/{project_id}/spec", json=spec)

    assert put.status_code == 422, put.text
    assert {i["path"] for i in put.json()["details"]} == {"auth.token_store", "auth.deletion_mode"}


async def test_invite_only_projects_generate_the_invitation_routes(client: AsyncClient) -> None:
    project_id = await make_project(client, "Club")
    await make_entity(client, project_id, "Post")
    await make_auth(client, project_id, invite_only=True)

    without_admin = (await client.post(f"/projects/{project_id}/validate")).json()
    await make_role(client, project_id, "admin")
    await make_role(client, project_id, "vip", invite_only=True)
    await make_role(client, project_id, "helper", self_assignable=True)
    with_admin = (await client.post(f"/projects/{project_id}/validate")).json()
    download = await client.get(f"/projects/{project_id}/generate/download")

    assert [(i["path"], i["code"]) for i in without_admin["issues"]] == [
        ("auth.registration.invite_only", "unknown_reference")
    ]
    assert with_admin == {"valid": True, "issues": []}
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        router = archive.read("club/app/auth/router.py").decode()
        assert '"/invitations"' in router
        schemas = archive.read("club/app/auth/schemas.py").decode()
        assert "invite_token" in schemas
        assert "'helper'" in schemas  # the self-assignable role can be picked at sign-up
        config_py = archive.read("club/app/auth/config.py").decode()
        assert "INVITE_ONLY = True" in config_py
        assert "tests/test_invitations.py" in "".join(archive.namelist())


async def test_multi_tenant_projects_generate_tenant_scoping(client: AsyncClient) -> None:
    project_id = await make_project(client, "Workspace")
    task = await make_entity(client, project_id, "Task")
    await make_auth(client, project_id, multi_tenant=True)
    await make_role(client, project_id, "admin")
    await make_role(client, project_id, "member", is_default=True)
    await client.post(
        f"/projects/{project_id}/permissions",
        json={
            "permissions": [
                {"entity_id": task, "operation": "list", "roles": ["member"], "row_rule": "tenant"}
            ]
        },
    )

    validation = (await client.post(f"/projects/{project_id}/validate")).json()
    download = await client.get(f"/projects/{project_id}/generate/download")

    assert validation == {"valid": True, "issues": []}
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        names = archive.namelist()
        assert "workspace/tests/test_tenancy.py" in names
        assert "tenant_name" in archive.read("workspace/app/auth/schemas.py").decode()
        assert "tenant=True" in archive.read("workspace/app/routers/tasks.py").decode()
        assert "tenant_id" in archive.read("workspace/alembic/versions/0002_auth.py").decode()


async def test_multi_tenancy_conflicts_with_invite_only_sign_up(client: AsyncClient) -> None:
    project_id = await make_project(client, "Clash")
    await make_entity(client, project_id, "Task")
    await make_auth(client, project_id, multi_tenant=True, invite_only=True)
    await make_role(client, project_id, "admin")

    validation = (await client.post(f"/projects/{project_id}/validate")).json()

    assert ("auth.multi_tenant", "invalid_value") in [
        (i["path"], i["code"]) for i in validation["issues"]
    ]
