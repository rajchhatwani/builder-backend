"""The Keycloak settings API and the guarded switch between built-in auth and Keycloak."""

import io
import uuid
import zipfile
from typing import Any

from httpx import AsyncClient

from tests.api._auth_helpers import make_auth, make_entity, make_project, make_role

TENANT = "11111111-2222-3333-4444-555555555555"


def settings(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "mode": "own",
        "redirect_uris": ["http://localhost:3000/"],
        "identity_providers": [
            {"alias": "google", "type": "google", "client_id": "abc.apps.example"},
            {"alias": "work", "type": "microsoft", "client_id": "cid", "tenant_id": TENANT},
        ],
    }
    body.update(overrides)
    return body


async def enable(client: AsyncClient, project_id: str, confirm: bool = True) -> Any:
    return await client.post(f"/projects/{project_id}/keycloak/enable", json={"confirm": confirm})


async def disable(client: AsyncClient, project_id: str, confirm: bool = True) -> Any:
    return await client.post(f"/projects/{project_id}/keycloak/disable", json={"confirm": confirm})


# --- settings ---------------------------------------------------------------------------


async def test_settings_start_empty(client: AsyncClient) -> None:
    project_id = await make_project(client)
    response = await client.get(f"/projects/{project_id}/keycloak")
    assert response.status_code == 404


async def test_put_fills_defaults_from_the_project_slug(client: AsyncClient) -> None:
    project_id = await make_project(client, "Shop Floor")

    response = await client.put(f"/projects/{project_id}/keycloak", json=settings())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["realm"] == "shop-floor"
    assert body["api_client_id"] == "shop-floor-api"
    assert body["web_client_id"] == "shop-floor-web"
    assert body["mode"] == "own"
    assert body["mfa"] == "optional"
    assert body["password_min_length"] == 12
    assert body["active"] is False
    assert [p["alias"] for p in body["identity_providers"]] == ["google", "work"]


async def test_put_replaces_and_get_returns_it(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/keycloak", json=settings())

    response = await client.put(
        f"/projects/{project_id}/keycloak",
        json=settings(realm="acme", mfa="required", identity_providers=[]),
    )

    assert response.status_code == 200
    got = (await client.get(f"/projects/{project_id}/keycloak")).json()
    assert got["realm"] == "acme"
    assert got["mfa"] == "required"
    assert got["identity_providers"] == []


async def test_put_rejects_wrong_shapes(client: AsyncClient) -> None:
    project_id = await make_project(client)
    for bad in ({"mode": "maybe"}, {"mfa": "sometimes"}, {"password_min_length": 0}):
        response = await client.put(f"/projects/{project_id}/keycloak", json=settings(**bad))
        assert response.status_code == 422, bad


async def test_settings_never_contain_secrets(client: AsyncClient) -> None:
    project_id = await make_project(client)
    body = settings(
        identity_providers=[
            {
                "alias": "google",
                "type": "google",
                "client_id": "abc",
                "client_secret": "super-secret",
            }
        ]
    )
    response = await client.put(f"/projects/{project_id}/keycloak", json=body)
    assert response.status_code == 200
    assert "super-secret" not in response.text
    assert "client_secret" not in response.text


async def test_unknown_project_is_404(client: AsyncClient) -> None:
    response = await client.put(f"/projects/{uuid.uuid4()}/keycloak", json=settings())
    assert response.status_code == 404


# --- switching --------------------------------------------------------------------------


async def test_enable_needs_saved_settings(client: AsyncClient) -> None:
    project_id = await make_project(client)
    response = await enable(client, project_id)
    assert response.status_code == 409
    assert response.json()["code"] == "invalid_state"


async def test_switching_needs_explicit_confirmation(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/keycloak", json=settings())

    response = await enable(client, project_id, confirm=False)

    assert response.status_code == 422
    assert response.json()["code"] == "confirmation_required"
    assert (await client.get(f"/projects/{project_id}/keycloak")).json()["active"] is False


async def test_enable_creates_the_auth_block_and_flips_the_provider(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/keycloak", json=settings())

    response = await enable(client, project_id)

    assert response.status_code == 200, response.text
    assert response.json()["active"] is True
    auth = (await client.get(f"/projects/{project_id}/auth")).json()
    assert auth["provider"] == "keycloak"
    assert auth["enabled"] is True


async def test_enable_keeps_an_existing_auth_block(client: AsyncClient) -> None:
    project_id = await make_project(client)
    created = await make_auth(client, project_id, access_token_ttl_minutes=30)
    await client.put(f"/projects/{project_id}/keycloak", json=settings())

    await enable(client, project_id)

    auth = (await client.get(f"/projects/{project_id}/auth")).json()
    assert auth["id"] == created["id"]
    assert auth["access_token_ttl_minutes"] == 30
    assert auth["provider"] == "keycloak"


async def test_enabling_twice_is_refused(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/keycloak", json=settings())
    await enable(client, project_id)
    assert (await enable(client, project_id)).status_code == 409


async def test_disable_keeps_the_settings_so_enabling_restores_them(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/keycloak", json=settings(realm="acme"))
    await enable(client, project_id)

    response = await disable(client, project_id)

    assert response.status_code == 200
    body = response.json()
    assert body["active"] is False
    assert body["realm"] == "acme"
    assert [p["alias"] for p in body["identity_providers"]] == ["google", "work"]
    assert (await client.get(f"/projects/{project_id}/auth")).json()["provider"] == "builtin"

    again = await enable(client, project_id)
    assert again.status_code == 200
    assert again.json()["realm"] == "acme"


async def test_disable_needs_confirmation_and_an_active_provider(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/keycloak", json=settings())
    assert (await disable(client, project_id)).status_code == 409  # not on yet
    await enable(client, project_id)
    unconfirmed = await disable(client, project_id, confirm=False)
    assert unconfirmed.status_code == 422
    assert (await client.get(f"/projects/{project_id}/keycloak")).json()["active"] is True


async def test_the_provider_cannot_be_changed_through_the_auth_endpoint(
    client: AsyncClient,
) -> None:
    project_id = await make_project(client)
    await make_auth(client, project_id)
    await client.patch(f"/projects/{project_id}/auth", json={"provider": "keycloak"})
    assert (await client.get(f"/projects/{project_id}/auth")).json()["provider"] == "builtin"


async def test_impact_reports_what_will_happen(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await client.put(f"/projects/{project_id}/keycloak", json=settings())

    on = (await client.get(f"/projects/{project_id}/keycloak/impact?action=enable")).json()
    assert on["can_proceed"] is True
    assert on["blockers"] == []
    assert any("AUTH_ALLOW_PROVIDER_SWITCH" in w for w in on["warnings"])

    off = (await client.get(f"/projects/{project_id}/keycloak/impact?action=disable")).json()
    assert off["can_proceed"] is False  # not on yet

    bad = await client.get(f"/projects/{project_id}/keycloak/impact?action=explode")
    assert bad.status_code == 422


# --- shared realm and dependents --------------------------------------------------------


async def make_shared(client: AsyncClient, source_id: str, name: str = "Portal") -> str:
    project_id = await make_project(client, name)
    response = await client.put(
        f"/projects/{project_id}/keycloak",
        json=settings(mode="shared", identity_providers=[], source_project_id=source_id),
    )
    assert response.status_code == 200, response.text
    return project_id


async def test_shared_project_takes_the_realm_of_its_source(client: AsyncClient) -> None:
    hub = await make_project(client, "Hub")
    await client.put(f"/projects/{hub}/keycloak", json=settings(realm="company"))

    portal = await make_shared(client, hub)

    got = (await client.get(f"/projects/{portal}/keycloak")).json()
    assert got["realm"] == "company"
    assert got["source_project_id"] == hub
    assert got["mode"] == "shared"


async def test_source_must_run_its_own_keycloak(client: AsyncClient) -> None:
    hub = await make_project(client, "Hub")
    portal = await make_project(client, "Portal")
    # The hub has no settings at all.
    response = await client.put(
        f"/projects/{portal}/keycloak",
        json=settings(mode="shared", identity_providers=[], source_project_id=hub),
    )
    assert response.status_code == 422

    # A project cannot point at itself, and only shared mode has a source.
    own = await client.put(f"/projects/{portal}/keycloak", json=settings(source_project_id=hub))
    assert own.status_code == 422
    selfref = await client.put(
        f"/projects/{portal}/keycloak",
        json=settings(mode="shared", identity_providers=[], source_project_id=portal),
    )
    assert selfref.status_code == 422


async def test_a_realm_with_dependents_cannot_be_switched_off(client: AsyncClient) -> None:
    hub = await make_project(client, "Hub")
    await client.put(f"/projects/{hub}/keycloak", json=settings(realm="company"))
    await enable(client, hub)
    portal = await make_shared(client, hub)
    await enable(client, portal)

    impact = (await client.get(f"/projects/{hub}/keycloak/impact?action=disable")).json()
    assert impact["can_proceed"] is False
    assert [d["name"] for d in impact["dependents"]] == ["Portal"]

    response = await disable(client, hub)
    assert response.status_code == 409
    assert response.json()["code"] == "has_dependents"
    assert "Portal" in response.json()["message"]
    assert (await client.get(f"/projects/{hub}/keycloak")).json()["active"] is True

    # Once the dependent moves back to built-in auth, the hub can follow.
    assert (await disable(client, portal)).status_code == 200
    assert (await disable(client, hub)).status_code == 200


async def test_a_realm_with_dependents_cannot_be_renamed_or_made_shared(
    client: AsyncClient,
) -> None:
    hub = await make_project(client, "Hub")
    await client.put(f"/projects/{hub}/keycloak", json=settings(realm="company"))
    await enable(client, hub)
    portal = await make_shared(client, hub)
    await enable(client, portal)

    renamed = await client.put(f"/projects/{hub}/keycloak", json=settings(realm="other"))
    assert renamed.status_code == 409
    assert renamed.json()["code"] == "has_dependents"

    # Changing something that does not define the realm is fine.
    ok = await client.put(
        f"/projects/{hub}/keycloak", json=settings(realm="company", mfa="required")
    )
    assert ok.status_code == 200


async def test_a_disabled_dependent_does_not_block(client: AsyncClient) -> None:
    hub = await make_project(client, "Hub")
    await client.put(f"/projects/{hub}/keycloak", json=settings(realm="company"))
    await enable(client, hub)
    await make_shared(client, hub)  # saved but never switched on

    assert (await disable(client, hub)).status_code == 200


async def test_deleting_the_source_project_unlinks_dependents(client: AsyncClient) -> None:
    hub = await make_project(client, "Hub")
    await client.put(f"/projects/{hub}/keycloak", json=settings(realm="company"))
    portal = await make_shared(client, hub)

    assert (await client.delete(f"/projects/{hub}")).status_code == 204

    got = (await client.get(f"/projects/{portal}/keycloak")).json()
    assert got["source_project_id"] is None
    assert got["realm"] == "company"


# --- through the whole builder: spec, validation, generation ------------------------------


async def build_hub(client: AsyncClient) -> str:
    """A project with an entity, roles and Keycloak switched on."""
    project_id = await make_project(client, "Hub")
    entity = await make_entity(client, project_id, "Note")
    created = await client.post(
        f"/entities/{entity}/fields",
        json={"name": "title", "type": "string", "required": True, "max_length": 100},
    )
    assert created.status_code == 201, created.text
    await make_role(client, project_id, "admin", position=0)
    await make_role(client, project_id, "member", is_default=True, position=1)
    saved = await client.put(f"/projects/{project_id}/keycloak", json=settings(realm="hub"))
    assert saved.status_code == 200, saved.text
    assert (await enable(client, project_id)).status_code == 200
    return project_id


async def test_the_spec_carries_provider_and_settings(client: AsyncClient) -> None:
    project_id = await build_hub(client)

    spec = (await client.get(f"/projects/{project_id}/spec")).json()

    assert spec["auth"]["provider"] == "keycloak"
    keycloak = spec["auth"]["keycloak"]
    assert keycloak["realm"] == "hub" and keycloak["mode"] == "own"
    assert keycloak["redirect_uris"] == ["http://localhost:3000/"]
    assert [p["alias"] for p in keycloak["identity_providers"]] == ["google", "work"]
    assert "source_project_id" not in keycloak  # builder bookkeeping, not part of the spec


async def test_a_keycloak_project_validates_clean(client: AsyncClient) -> None:
    project_id = await build_hub(client)

    response = await client.post(f"/projects/{project_id}/validate")

    assert response.json() == {"valid": True, "issues": []}


async def test_validate_names_what_is_wrong_with_the_keycloak_settings(
    client: AsyncClient,
) -> None:
    project_id = await build_hub(client)
    await client.put(
        f"/projects/{project_id}/keycloak",
        json=settings(
            realm="hub",
            redirect_uris=["https://app.example.com/*"],
            identity_providers=[{"alias": "work", "type": "microsoft", "client_id": "x"}],
        ),
    )

    issues = (await client.post(f"/projects/{project_id}/validate")).json()["issues"]

    paths = {i["path"] for i in issues}
    assert "auth.keycloak.redirect_uris[0]" in paths
    assert "auth.keycloak.identity_providers[0].tenant_id" in paths


async def test_spec_round_trip_keeps_keycloak_and_the_provider(client: AsyncClient) -> None:
    project_id = await build_hub(client)
    spec = (await client.get(f"/projects/{project_id}/spec")).json()
    copy_id = await make_project(client, "Hub Copy")

    imported = await client.put(f"/projects/{copy_id}/spec", json=spec)

    assert imported.status_code == 200, imported.text
    again = (await client.get(f"/projects/{copy_id}/spec")).json()
    spec["project"] = again["project"]
    assert again == spec
    assert (await client.get(f"/projects/{copy_id}/keycloak")).json()["active"] is True


async def test_the_settings_survive_going_back_to_builtin(client: AsyncClient) -> None:
    project_id = await build_hub(client)
    assert (await disable(client, project_id)).status_code == 200

    spec = (await client.get(f"/projects/{project_id}/spec")).json()

    assert spec["auth"]["provider"] == "builtin"
    assert spec["auth"]["keycloak"]["realm"] == "hub"  # kept, so switching back is lossless


async def test_download_contains_the_realm_and_no_secret(client: AsyncClient) -> None:
    project_id = await build_hub(client)

    response = await client.get(f"/projects/{project_id}/generate/download")

    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = {n.split("/", 1)[1] for n in archive.namelist()}  # inside the hub/ folder
        assert {"keycloak/realm.json", "scripts/keycloak_register.py"} <= names
        assert "app/auth/oidc.py" in names and "app/auth/security.py" not in names
        blob = b"".join(archive.read(n) for n in archive.namelist()).decode(
            "utf-8", errors="replace"
        )
    assert "${KC_IDP_GOOGLE_CLIENT_SECRET}" in blob
    assert "BEGIN PRIVATE KEY" not in blob


async def test_a_project_switched_back_generates_without_keycloak(client: AsyncClient) -> None:
    project_id = await build_hub(client)
    await disable(client, project_id)

    response = await client.get(f"/projects/{project_id}/generate/download")

    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = {n.split("/", 1)[1] for n in archive.namelist()}
    assert not [n for n in names if n.startswith("keycloak/")]
    assert "app/auth/security.py" in names
