import uuid

import pytest
from httpx import AsyncClient

from tests.api._auth_helpers import SMTP, auth_body, make_auth, make_project


async def test_create_returns_defaults(client: AsyncClient) -> None:
    project_id = await make_project(client)

    response = await client.post(f"/projects/{project_id}/auth", json=auth_body())

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["project_id"] == project_id
    assert body["enabled"] is True
    assert body["token_store"] == "db"
    assert body["jwt_algorithm"] == "HS256"
    assert body["access_token_ttl_minutes"] == 15
    assert body["refresh_token_ttl_days"] == 7
    assert body["deletion_mode"] == "soft"
    assert body["email_verification_required"] is True
    assert body["smtp_config"] == SMTP
    assert body["login_rate_limit"] == "5/15minutes"


async def test_the_default_rate_limits_can_be_sent_back(client: AsyncClient) -> None:
    """Regression: the grammar used to reject its own default ('5/15minutes')."""
    project_id = await make_project(client)
    created = await make_auth(client, project_id)

    response = await client.patch(
        f"/projects/{project_id}/auth",
        json={
            "login_rate_limit": created["login_rate_limit"],
            "register_rate_limit": created["register_rate_limit"],
            "reset_rate_limit": created["reset_rate_limit"],
        },
    )

    assert response.status_code == 200, response.text


@pytest.mark.parametrize("limit", ["5/minute", "10/hour", "5/15minutes", "100/day", "1/second"])
async def test_valid_rate_limits(client: AsyncClient, limit: str) -> None:
    project_id = await make_project(client)
    response = await client.post(
        f"/projects/{project_id}/auth", json=auth_body(login_rate_limit=limit)
    )
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("limit", ["", "5", "five/minute", "5/week", "5/minute; drop table"])
async def test_invalid_rate_limits(client: AsyncClient, limit: str) -> None:
    project_id = await make_project(client)
    response = await client.post(
        f"/projects/{project_id}/auth", json=auth_body(login_rate_limit=limit)
    )
    assert response.status_code == 422


async def test_second_create_conflicts(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await make_auth(client, project_id)

    response = await client.post(f"/projects/{project_id}/auth", json=auth_body())

    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


async def test_get_before_create_is_404(client: AsyncClient) -> None:
    project_id = await make_project(client)

    response = await client.get(f"/projects/{project_id}/auth")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_unknown_project_is_404_everywhere(client: AsyncClient) -> None:
    missing = uuid.uuid4()
    assert (await client.post(f"/projects/{missing}/auth", json=auth_body())).status_code == 404
    assert (await client.get(f"/projects/{missing}/auth")).status_code == 404
    assert (await client.patch(f"/projects/{missing}/auth", json={})).status_code == 404


async def test_email_magic_link_requires_smtp(client: AsyncClient) -> None:
    project_id = await make_project(client)

    response = await client.post(f"/projects/{project_id}/auth", json={})

    assert response.status_code == 422
    assert "smtp_config" in response.text


async def test_sms_otp_requires_provider_and_config(client: AsyncClient) -> None:
    project_id = await make_project(client)

    response = await client.post(
        f"/projects/{project_id}/auth", json=auth_body(sms_otp_enabled=True)
    )

    assert response.status_code == 422
    assert "sms_provider" in response.text


async def test_sms_otp_with_provider_is_accepted(client: AsyncClient) -> None:
    project_id = await make_project(client)

    response = await client.post(
        f"/projects/{project_id}/auth",
        json=auth_body(
            sms_otp_enabled=True, sms_provider="twilio", sms_config={"from_number": "+14155550100"}
        ),
    )

    assert response.status_code == 201, response.text
    assert response.json()["sms_provider"] == "twilio"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("access_token_ttl_minutes", 0),
        ("access_token_ttl_minutes", 1441),
        ("refresh_token_ttl_days", 0),
        ("refresh_token_ttl_days", 366),
        ("otp_ttl_minutes", 0),
        ("otp_ttl_minutes", 61),
        ("jwt_algorithm", "none"),
        ("token_store", "memcached"),
        ("deletion_mode", "shred"),
        ("sms_provider", "carrier_pigeon"),
    ],
)
async def test_out_of_range_values_are_rejected(
    client: AsyncClient, field: str, value: object
) -> None:
    project_id = await make_project(client)

    response = await client.post(f"/projects/{project_id}/auth", json=auth_body(**{field: value}))

    assert response.status_code == 422, response.text


async def test_smtp_config_is_validated(client: AsyncClient) -> None:
    project_id = await make_project(client)
    bad = {**SMTP, "from_email": "not-an-address", "port": 70000}

    response = await client.post(f"/projects/{project_id}/auth", json=auth_body(smtp_config=bad))

    assert response.status_code == 422


async def test_patch_updates_only_the_given_fields(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await make_auth(client, project_id)

    response = await client.patch(
        f"/projects/{project_id}/auth",
        json={"access_token_ttl_minutes": 60, "deletion_mode": "hard"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token_ttl_minutes"] == 60
    assert body["deletion_mode"] == "hard"
    assert body["refresh_token_ttl_days"] == 7
    assert body["smtp_config"] == SMTP
    assert (await client.get(f"/projects/{project_id}/auth")).json() == body


async def test_patch_enabling_sms_without_provider_is_rejected_and_not_saved(
    client: AsyncClient,
) -> None:
    project_id = await make_project(client)
    await make_auth(client, project_id)

    response = await client.patch(f"/projects/{project_id}/auth", json={"sms_otp_enabled": True})

    assert response.status_code == 422
    assert (await client.get(f"/projects/{project_id}/auth")).json()["sms_otp_enabled"] is False


async def test_patch_can_replace_smtp_settings(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await make_auth(client, project_id)
    replacement = {**SMTP, "host": "smtp.other.example", "port": 465}

    response = await client.patch(f"/projects/{project_id}/auth", json={"smtp_config": replacement})

    assert response.status_code == 200, response.text
    assert response.json()["smtp_config"] == replacement


async def test_config_is_removed_with_its_project(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await make_auth(client, project_id)

    assert (await client.delete(f"/projects/{project_id}")).status_code == 204

    assert (await client.get(f"/projects/{project_id}/auth")).status_code == 404
