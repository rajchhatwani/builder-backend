"""Scenarios run INSIDE the generated `providers_notify` project (copied to tests/test_scenarios.py by
tests/e2e/test_providers_stack.py) against a real Postgres: the vault API as admin / non-admin / another
tenant, key rotation with the re-encrypt command as a real process, the emulator and the breaker, and
a production start-up that must refuse a missing or weak master key. No real provider is ever called."""

import os
import subprocess
import sys

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from app.db import session_factory
from app.providers import client as provider_client
from app.providers import definitions, schemas, vault
from app.providers.errors import CircuitOpen, Retryable
from app.providers.models import ProviderCredential
from tests._auth_support import outbox, sign_in, sign_in_plain  # noqa: F401
from tests._providers_support import KEY_1, KEY_2, emulator, vault_env  # noqa: F401

CANARY = "CANARY-e2e-5d8c2a71f94e03b6a1d7-do-not-leak"
URL = "/providers/credentials/acme_mail/api_key"


def _child(extra: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    for name in ("PROVIDER_VAULT_KEY", "PROVIDER_VAULT_KEY_VERSION", "PROVIDER_VAULT_KEY_PREVIOUS", "APP_ENV"):
        env.pop(name, None)
    env.update(extra)
    return subprocess.run([sys.executable, *args], env=env, capture_output=True, text=True, timeout=120)


async def _rows() -> list[ProviderCredential]:
    async with session_factory() as session:
        return list((await session.execute(sa.select(ProviderCredential))).scalars())


async def test_vault_round_trip_denial_and_tenant_isolation(client: AsyncClient, outbox, vault_env) -> None:  # noqa: ANN001, F811
    first = await sign_in(client, "first@example.com", roles=["admin"])
    second = await sign_in(client, "second@example.com", roles=["admin"])
    plain = await sign_in_plain(client, "plain@example.com")
    put = await client.put(URL, json={"value": CANARY}, headers=first)
    assert put.status_code == 200 and CANARY not in put.text
    assert [c["key_name"] for c in (await client.get("/providers/credentials", headers=first)).json()] == ["api_key"]
    assert (await client.get("/providers/credentials", headers=second)).json() == []
    assert (await client.delete(URL, headers=second)).status_code == 404
    for headers in (plain, {}):
        status = 403 if headers else 401
        assert (await client.get("/providers/credentials", headers=headers)).status_code == status
        assert (await client.put(URL, json={"value": CANARY}, headers=headers)).status_code == status
    rows = await _rows()
    assert len(rows) == 1 and CANARY not in rows[0].ciphertext
    assert (await client.delete(URL, headers=first)).status_code == 204
    assert await _rows() == []


async def test_rotation_with_the_reencrypt_command(client: AsyncClient, outbox, vault_env) -> None:  # noqa: ANN001, F811
    admin = await sign_in(client, "admin@example.com", roles=["admin"])
    assert (await client.put(URL, json={"value": CANARY}, headers=admin)).status_code == 200
    assert [r.key_version for r in await _rows()] == [1]
    rotated = {"PROVIDER_VAULT_KEY": KEY_2, "PROVIDER_VAULT_KEY_VERSION": "2", "PROVIDER_VAULT_KEY_PREVIOUS": f"1={KEY_1}"}
    done = _child(rotated, "-m", "app.providers.reencrypt")
    assert done.returncode == 0 and "re-encrypted 1 credential(s)" in done.stdout, done.stderr
    assert CANARY not in done.stdout + done.stderr and KEY_1 not in done.stdout + done.stderr
    assert "re-encrypted 0 credential(s)" in _child(rotated, "-m", "app.providers.reencrypt").stdout
    assert [r.key_version for r in await _rows()] == [2]
    # the old key is no longer needed; the credential still opens with the new one only
    vault_env.setenv("PROVIDER_VAULT_KEY", KEY_2)
    vault_env.setenv("PROVIDER_VAULT_KEY_VERSION", "2")
    async with session_factory() as session:
        tenant = (await _rows())[0].tenant_id
        assert (await vault.load(session, tenant, "acme_mail")).get("api_key") == CANARY
    # without the previous key the command reports a clear error and leaves the rows alone
    refused = _child({"PROVIDER_VAULT_KEY": KEY_1, "PROVIDER_VAULT_KEY_VERSION": "3"}, "-m", "app.providers.reencrypt")
    assert refused.returncode != 0 and CANARY not in refused.stdout + refused.stderr
    assert KEY_1 not in refused.stdout + refused.stderr and KEY_2 not in refused.stdout + refused.stderr


async def test_the_emulator_receives_messages_and_the_breaker_opens(emulator, monkeypatch) -> None:  # noqa: ANN001, F811
    tenant = await _tenant()
    mail = schemas.EmailRequest(to="ann@example.com", subject="Hi", body="Hello")
    monkeypatch.setattr(definitions, "MAX_ATTEMPTS", 1)
    monkeypatch.setattr(definitions, "BREAKER_FAILURES", 2)  # read when a tenant's breaker is first used
    async with session_factory() as session:
        assert (await provider_client.call_provider(session, tenant, "email", mail)).message_id == "emu-email-000001"
        assert emulator.sent["email"][0].request["to"] == "ann@example.com"
        emulator.inject("email", "retryable", times=2)
        for _ in range(2):
            with pytest.raises(Retryable):
                await provider_client.call_provider(session, tenant, "email", mail)
        calls = emulator.calls["email"]
        with pytest.raises(CircuitOpen):
            await provider_client.call_provider(session, tenant, "email", mail)
        assert emulator.calls["email"] == calls


async def _tenant():  # noqa: ANN202
    import uuid

    return uuid.UUID("33333333-3333-4333-8333-333333333333")


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"PROVIDER_VAULT_KEY": "too-short"},
        {"PROVIDER_VAULT_KEY": "changeme-" + "ab12cd34" * 4},
        {"PROVIDER_VAULT_KEY": "a" * 40},
    ],
)
def test_production_start_up_refuses_a_missing_or_weak_master_key(extra: dict[str, str]) -> None:
    code = (
        "import asyncio\n"
        "from app.main import app, lifespan\n"
        "async def go():\n"
        "    async with lifespan(app):\n"
        "        pass\n"
        "asyncio.run(go())\n"
    )
    result = _child({"APP_ENV": "production", "AUTH_JWT_SECRET": "x" * 40, **extra}, "-c", code)
    assert result.returncode != 0
    assert "PROVIDER_VAULT_KEY" in result.stderr
    for value in extra.values():
        assert value not in result.stdout + result.stderr
