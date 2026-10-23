"""The storage settings API, its guarded switch, the spec round trip and the `file` field type."""

from typing import Any

from httpx import AsyncClient

from tests.api._auth_helpers import make_auth, make_project
from tests.unit.test_storage_validation import base_spec


def settings(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "backend": "s3",
        "bucket": "team-uploads",
        "region": "eu-west-1",
        "roles": {
            "upload": ["member"],
            "read": ["member"],
            "delete": ["member"],
            "operate": ["admin"],
        },
    }
    body.update(overrides)
    return body


async def enable(client: AsyncClient, project_id: str, confirm: bool = True) -> Any:
    return await client.post(f"/projects/{project_id}/storage/enable", json={"confirm": confirm})


async def disable(client: AsyncClient, project_id: str, confirm: bool = True) -> Any:
    return await client.post(f"/projects/{project_id}/storage/disable", json={"confirm": confirm})


async def test_settings_start_empty(client: AsyncClient) -> None:
    project_id = await make_project(client)
    assert (await client.get(f"/projects/{project_id}/storage")).status_code == 404


async def test_put_creates_settings_with_safe_defaults_and_does_not_switch_storage_on(
    client: AsyncClient,
) -> None:
    project_id = await make_project(client)

    response = await client.put(f"/projects/{project_id}/storage", json=settings())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is False
    assert body["max_file_mb"] == 25
    assert body["allowed_types"] == []  # any type; the content is still checked and scanned
    assert body["download_mode"] == "proxy"
    assert body["allow_inline_images"] is False
    assert body["security"]["audit_retention_days"] == 2555
    assert body["roles"]["share"] == [] and body["roles"]["read_all"] == []  # nobody unless listed


async def test_put_replaces_and_get_returns_it(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/storage", json=settings())

    await client.put(
        f"/projects/{project_id}/storage",
        json=settings(
            backend="minio", bucket="other-bucket", allowed_types=["image/*"], max_file_mb=5
        ),
    )

    got = (await client.get(f"/projects/{project_id}/storage")).json()
    assert got["backend"] == "minio" and got["bucket"] == "other-bucket"
    assert got["allowed_types"] == ["image/*"] and got["max_file_mb"] == 5


async def test_put_rejects_wrong_shapes(client: AsyncClient) -> None:
    project_id = await make_project(client)
    for bad in (
        {"backend": "ftp"},
        {"download_mode": "teleport"},
        {"max_file_mb": 0},
        {"bucket": "x" * 64},
        {"uploads_per_hour": 0},
        {"roles": {"upload": "member"}},
    ):
        response = await client.put(f"/projects/{project_id}/storage", json=settings(**bad))
        assert response.status_code == 422, bad


async def test_there_is_no_field_that_could_hold_a_bucket_credential(client: AsyncClient) -> None:
    project_id = await make_project(client)
    for key in ("access_key", "secret_key", "STORAGE_SECRET_ACCESS_KEY", "password"):
        response = await client.put(
            f"/projects/{project_id}/storage", json=settings(**{key: "AKIA-very-secret-value"})
        )
        # Unknown fields are ignored by the schema, and must never be echoed back or stored.
        assert response.status_code == 200
        assert "AKIA-very-secret-value" not in response.text
    assert "AKIA" not in (await client.get(f"/projects/{project_id}/storage")).text
    assert "AKIA" not in (await client.get(f"/projects/{project_id}/spec")).text


async def test_unknown_project_is_404(client: AsyncClient) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/projects/{missing}/storage")).status_code == 404
    assert (await client.put(f"/projects/{missing}/storage", json=settings())).status_code == 404


# --- the switch ---------------------------------------------------------------------------


async def test_enable_needs_confirmation_settings_and_auth(client: AsyncClient) -> None:
    project_id = await make_project(client)

    unconfirmed = await enable(client, project_id, confirm=False)
    assert unconfirmed.status_code == 422
    assert unconfirmed.json()["code"] == "confirmation_required"

    no_settings = await enable(client, project_id)
    assert no_settings.status_code == 409
    assert "Save the storage settings" in no_settings.json()["message"]

    await client.put(f"/projects/{project_id}/storage", json=settings())
    no_auth = await enable(client, project_id)
    assert no_auth.status_code == 409
    assert "authentication" in no_auth.json()["message"]

    await make_auth(client, project_id)
    ok = await enable(client, project_id)
    assert ok.status_code == 200, ok.text
    assert ok.json()["enabled"] is True


async def test_impact_reports_before_anything_changes(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/storage", json=settings())
    await make_auth(client, project_id)

    impact = (await client.get(f"/projects/{project_id}/storage/impact?action=enable")).json()
    assert impact["can_proceed"] is True and impact["enabled"] is False
    assert any("malware" in w for w in impact["warnings"])
    assert any("environment variables" in w for w in impact["warnings"])

    await enable(client, project_id)
    assert (await client.get(f"/projects/{project_id}/storage/impact?action=enable")).json()[
        "can_proceed"
    ] is False

    off = (await client.get(f"/projects/{project_id}/storage/impact?action=disable")).json()
    assert off["can_proceed"] is True
    assert any("never removed" in w for w in off["warnings"])

    assert (
        await client.get(f"/projects/{project_id}/storage/impact?action=explode")
    ).status_code == 422


async def test_disable_keeps_the_settings_and_saving_does_not_flip_the_switch(
    client: AsyncClient,
) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/storage", json=settings(bucket="keep-me"))
    await make_auth(client, project_id)
    await enable(client, project_id)

    saved = await client.put(f"/projects/{project_id}/storage", json=settings(bucket="keep-me"))
    assert saved.json()["enabled"] is True  # saving again while on leaves it on

    assert (await disable(client, project_id, confirm=False)).status_code == 422
    off = await disable(client, project_id)
    assert off.status_code == 200
    assert off.json()["enabled"] is False and off.json()["bucket"] == "keep-me"
    assert (await disable(client, project_id)).status_code == 409  # already off


async def test_issues_endpoint_lists_only_storage_problems(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/spec", json=base_spec())
    await client.put(f"/projects/{project_id}/storage", json=settings(bucket="BAD_NAME"))
    issues = (await client.get(f"/projects/{project_id}/storage/issues")).json()["issues"]
    assert any(i["path"] == "storage.bucket" for i in issues)
    assert all(i["path"].startswith("storage") or i["code"] == "storage_required" for i in issues)


# --- spec round trip --------------------------------------------------------------------------


async def test_storage_and_file_fields_survive_a_spec_round_trip_into_another_project(
    client: AsyncClient,
) -> None:
    first = await make_project(client, "First")
    imported = await client.put(
        f"/projects/{first}/spec", json=base_spec(allowed_types=["image/*"])
    )
    assert imported.status_code == 200, imported.text
    exported = (await client.get(f"/projects/{first}/spec")).json()
    assert exported["storage"]["enabled"] is True
    assert exported["storage"]["allowed_types"] == ["image/*"]
    types = {f["name"]: f["type"] for f in exported["entities"][0]["fields"]}
    assert types["image_id"] == "file"

    second = await make_project(client, "Second")
    copied = await client.put(f"/projects/{second}/spec", json=exported)
    assert copied.status_code == 200, copied.text
    assert (await client.get(f"/projects/{second}/spec")).json()["storage"] == exported["storage"]
    row = (await client.get(f"/projects/{second}/storage")).json()
    assert row["enabled"] is True and row["roles"]["upload"] == ["member"]


async def test_an_invalid_storage_block_is_refused_and_changes_nothing(client: AsyncClient) -> None:
    project_id = await make_project(client)
    data = base_spec()
    data["storage"]["bucket"] = "NOT VALID"
    refused = await client.put(f"/projects/{project_id}/spec", json=data)
    assert refused.status_code == 422
    assert any(d["path"] == "storage.bucket" for d in refused.json()["details"])
    assert (await client.get(f"/projects/{project_id}/storage")).status_code == 404


async def test_a_file_field_can_be_added_through_the_fields_api(client: AsyncClient) -> None:
    project_id = await make_project(client)
    entity = (await client.post(f"/projects/{project_id}/entities", json={"name": "Photo"})).json()
    created = await client.post(
        f"/entities/{entity['id']}/fields",
        json={"name": "image_id", "type": "file", "required": True},
    )
    assert created.status_code == 201, created.text
    assert created.json()["type"] == "file"
    found = (await client.post(f"/projects/{project_id}/validate")).json()
    issues = found["issues"] if isinstance(found, dict) else found
    assert any(i["code"] == "storage_required" for i in issues)  # needs storage first


async def test_generation_includes_the_storage_module_only_when_it_is_on(
    client: AsyncClient,
) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/spec", json=base_spec())
    preview = await client.post(f"/projects/{project_id}/generate/preview")
    assert preview.status_code == 200, preview.text
    paths = {f["path"] for f in preview.json()["files"]}
    assert {"app/storage/service.py", "alembic/versions/0004_storage.py"} <= paths
    assert "deploy/storage/STORAGE.md" in paths

    # Storage cannot be switched off while an entity still has a file field.
    await disable(client, project_id)
    refused = await client.post(f"/projects/{project_id}/generate/preview")
    assert refused.status_code == 422
    assert any(d["code"] == "storage_required" for d in refused.json()["details"])
