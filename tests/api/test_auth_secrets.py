import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.crypto import decrypt
from app.models.auth_secrets import ProjectAuthSecrets
from tests.api._auth_helpers import auth_body, make_auth, make_project

SMTP_SECRET = {"username": "mailer", "password": "smtp-pass-ZZ1"}
TWILIO_SECRET = {"account_sid": "ACZZ-sid-2", "auth_token": "ZZ-token-3"}
ALL_PLAINTEXT = ("smtp-pass-ZZ1", "ACZZ-sid-2", "ZZ-token-3", "mailer")


async def test_status_before_anything_is_stored_is_all_false(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await make_auth(client, project_id)

    response = await client.get(f"/projects/{project_id}/auth/secrets/status")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["smtp"] == {"configured": False, "username_set": False}
    assert body["sms"] == {"provider": None, "configured": False}


async def test_put_returns_status_booleans_never_plaintext(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await make_auth(
        client,
        project_id,
        sms_otp_enabled=True,
        sms_provider="twilio",
        sms_config={"from_number": "+14155550100"},
    )

    response = await client.put(
        f"/projects/{project_id}/auth/secrets", json={"smtp": SMTP_SECRET, "twilio": TWILIO_SECRET}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["smtp"] == {"configured": True, "username_set": True}
    assert body["sms"] == {"provider": "twilio", "configured": True}
    for secret in ALL_PLAINTEXT:
        assert secret not in response.text
    status = await client.get(f"/projects/{project_id}/auth/secrets/status")
    for secret in ALL_PLAINTEXT:
        assert secret not in status.text


async def test_secrets_are_encrypted_at_rest(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    project_id = await make_project(client)
    await make_auth(client, project_id)
    await client.put(f"/projects/{project_id}/auth/secrets", json={"smtp": SMTP_SECRET})

    async with session_factory() as session:
        row = (
            await session.execute(
                select(ProjectAuthSecrets).where(
                    ProjectAuthSecrets.project_id == uuid.UUID(project_id)
                )
            )
        ).scalar_one()

    assert row.smtp_password is not None and "smtp-pass-ZZ1" not in row.smtp_password
    assert row.smtp_username is not None and "mailer" not in row.smtp_username
    assert decrypt(row.smtp_password) == "smtp-pass-ZZ1"
    assert decrypt(row.smtp_username) == "mailer"


async def test_partial_update_leaves_other_groups_alone(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await make_auth(
        client,
        project_id,
        sms_otp_enabled=True,
        sms_provider="twilio",
        sms_config={"from_number": "+14155550100"},
    )
    await client.put(f"/projects/{project_id}/auth/secrets", json={"smtp": SMTP_SECRET})

    response = await client.put(
        f"/projects/{project_id}/auth/secrets", json={"twilio": TWILIO_SECRET}
    )

    body = response.json()
    assert body["smtp"]["configured"] is True
    assert body["sms"]["configured"] is True


async def test_smtp_without_a_username_is_configured_but_username_unset(
    client: AsyncClient,
) -> None:
    project_id = await make_project(client)
    await make_auth(client, project_id)

    response = await client.put(
        f"/projects/{project_id}/auth/secrets", json={"smtp": {"password": "only-a-key"}}
    )

    assert response.json()["smtp"] == {"configured": True, "username_set": False}


async def test_sms_status_follows_the_configured_provider(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await make_auth(
        client,
        project_id,
        sms_otp_enabled=True,
        sms_provider="vonage",
        sms_config={"from_number": "+14155550100"},
    )

    # Twilio keys do not satisfy a Vonage project.
    response = await client.put(
        f"/projects/{project_id}/auth/secrets", json={"twilio": TWILIO_SECRET}
    )
    assert response.json()["sms"] == {"provider": "vonage", "configured": False}

    response = await client.put(
        f"/projects/{project_id}/auth/secrets",
        json={"vonage": {"api_key": "k", "api_secret": "s"}},
    )
    assert response.json()["sms"] == {"provider": "vonage", "configured": True}


async def test_aws_sns_needs_all_three_values(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await make_auth(
        client,
        project_id,
        sms_otp_enabled=True,
        sms_provider="aws_sns",
        sms_config={"from_number": "ShopApp"},
    )

    incomplete = await client.put(
        f"/projects/{project_id}/auth/secrets",
        json={"aws_sns": {"access_key_id": "AKIA", "secret_access_key": "x"}},
    )
    complete = await client.put(
        f"/projects/{project_id}/auth/secrets",
        json={
            "aws_sns": {"access_key_id": "AKIA", "secret_access_key": "x", "region": "eu-west-1"}
        },
    )

    assert incomplete.status_code == 422
    assert complete.json()["sms"] == {"provider": "aws_sns", "configured": True}


async def test_declared_provider_requires_its_credential_block(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await make_auth(client, project_id)

    response = await client.put(
        f"/projects/{project_id}/auth/secrets",
        json={"sms_provider": "twilio", "vonage": {"api_key": "k", "api_secret": "s"}},
    )

    assert response.status_code == 422


async def test_blank_credentials_are_rejected(client: AsyncClient) -> None:
    project_id = await make_project(client)
    await make_auth(client, project_id)

    response = await client.put(
        f"/projects/{project_id}/auth/secrets", json={"smtp": {"password": ""}}
    )

    assert response.status_code == 422


async def test_unknown_project_is_404(client: AsyncClient) -> None:
    missing = uuid.uuid4()
    assert (
        await client.put(f"/projects/{missing}/auth/secrets", json={"smtp": SMTP_SECRET})
    ).status_code == 404
    assert (await client.get(f"/projects/{missing}/auth/secrets/status")).status_code == 404


async def test_secrets_can_be_stored_before_the_auth_config_exists(client: AsyncClient) -> None:
    project_id = await make_project(client)

    response = await client.put(f"/projects/{project_id}/auth/secrets", json={"smtp": SMTP_SECRET})

    assert response.status_code == 200, response.text
    assert response.json()["smtp"]["configured"] is True


async def test_missing_secret_key_fails_loudly_instead_of_storing_plaintext(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.core.crypto as crypto

    # Only the encryption layer loses its key here: with SECRET_KEY unset the builder cannot even
    # verify sign-in tokens (that is covered in test_platform_security), so the request would never
    # reach the secrets endpoint.
    def no_key() -> object:
        raise RuntimeError("SECRET_KEY environment variable is not set")

    monkeypatch.setattr(crypto, "_get_fernet", no_key)
    project_id = await make_project(client)
    await client.post(f"/projects/{project_id}/auth", json=auth_body())

    try:
        response = await client.put(
            f"/projects/{project_id}/auth/secrets", json={"smtp": SMTP_SECRET}
        )
    except RuntimeError as exc:
        # The ASGI test transport re-raises server errors; either way nothing was stored.
        assert "SECRET_KEY" in str(exc)
    else:
        assert response.status_code == 500
    status = await client.get(f"/projects/{project_id}/auth/secrets/status")
    assert status.json()["smtp"]["configured"] is False
