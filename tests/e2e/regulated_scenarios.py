"""Scenario tests for regulated mode (D40/D41/D43) in the generated `regulated_clients` project (copied into the
project's tests/ by tests/e2e/test_regulated_stack.py and run against a real Postgres).

Spec: Customer.email is encrypted and searchable (blind index), Customer.api_token is tokenised; events, webhooks,
jobs, providers and history (Order only) are on; key provider `file`.

Proves, with raw SQL against the real tables: ciphertext at rest, the blind-index equality filter, tokenisation and its
vault, key rotation (new key first, `reencrypt` moves every row, an early key drop fails closed and changes nothing,
the old key can be removed afterwards), the provider credential vault riding on the same keyring (P6, no
PROVIDER_VAULT_KEY), and that a unique marker value is in NO table of the database and NO log line."""

import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from app.db import session_factory
from app.providers import vault
from app.regulated import crypto, keys, tokens
from app.regulated.errors import RegulatedError
from app.regulated.reencrypt import reencrypt_all
from tests._auth_support import authed_client, outbox  # noqa: F401
from tests._regulated_support import key_line, write_keys

EMAIL = "zxq.marker.7431@example.com"
TOKEN_VALUE = "TOKMARKER-9988-7766-5544"


async def _create(client: AsyncClient, email: str = EMAIL, token: str | None = TOKEN_VALUE, name: str = "Ann") -> dict:
    body: dict[str, object] = {"name": name, "email": email}
    if token is not None:
        body["api_token"] = token
    response = await client.post("/customers", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _raw(sql: str, **params: object) -> list[sa.Row]:
    async with session_factory() as session:
        return list((await session.execute(sa.text(sql), params)).all())


async def test_ciphertext_at_rest_and_blind_index_lookup(authed_client: AsyncClient) -> None:  # noqa: F811
    created = await _create(authed_client)
    assert created["email"] == EMAIL  # the authorised caller gets the plaintext
    [(email, bidx, api_token)] = await _raw("SELECT email, email_bidx, api_token FROM customers WHERE id = :i", i=uuid.UUID(created["id"]))
    assert email.startswith("rg1:k2:") and EMAIL not in email  # ciphertext under the active key
    assert len(bidx) == 64 and EMAIL not in bidx  # a keyed hash, not the value
    assert tokens.is_token(api_token) and TOKEN_VALUE not in api_token
    assert created["api_token"] == api_token  # the API shows the token, never the original
    [(vaulted,)] = await _raw("SELECT ciphertext FROM regulated_tokens WHERE token = :t", t=api_token)
    assert vaulted.startswith("rg1:k2:") and TOKEN_VALUE not in vaulted

    found = await authed_client.get("/customers", params={"email": EMAIL})
    assert [i["id"] for i in found.json()["items"]] == [created["id"]]
    assert (await authed_client.get("/customers", params={"email": " " + EMAIL.upper()})).json()["total"] == 1  # normalised
    assert (await authed_client.get("/customers", params={"email": "someone.else@example.com"})).json()["total"] == 0

    moved = await authed_client.patch(f"/customers/{created['id']}", json={"email": "new.address@example.com"})
    assert moved.status_code == 200, moved.text
    assert (await authed_client.get("/customers", params={"email": EMAIL})).json()["total"] == 0
    assert (await authed_client.get("/customers", params={"email": "new.address@example.com"})).json()["total"] == 1
    [(email2,)] = await _raw("SELECT email FROM customers WHERE id = :i", i=uuid.UUID(created["id"]))
    assert email2.startswith("rg1:") and "new.address" not in email2

    async with session_factory() as session:  # the one way back from a token
        assert await tokens.detokenise(session, api_token) == TOKEN_VALUE


async def test_a_tokenised_value_gets_one_token_and_one_vault_row(authed_client: AsyncClient) -> None:  # noqa: F811
    first = await _create(authed_client, "a.one@example.com")
    second = await _create(authed_client, "a.two@example.com")
    assert first["api_token"] == second["api_token"]
    assert (await _raw("SELECT count(*) FROM regulated_tokens"))[0][0] == 1


async def test_key_rotation_reencrypts_every_row_and_an_early_key_drop_fails_closed(
    authed_client: AsyncClient,  # noqa: F811
    regulated_keys: Path,
) -> None:
    ids = [(await _create(authed_client, f"rot.{n}@example.com", token=f"ROTTOKEN-{n}-aaaa-bbbb"))["id"] for n in range(3)]
    assert {r[0].split(":")[1] for r in await _raw("SELECT email FROM customers")} == {"k2"}

    write_keys(regulated_keys, key_line("k3", 3), key_line("k2", 2), key_line("k1", 1))  # rotate: new key first
    fresh = await _create(authed_client, "rot.new@example.com", token=None)
    assert (await _raw("SELECT email FROM customers WHERE id = :i", i=uuid.UUID(fresh["id"])))[0][0].startswith("rg1:k3:")
    for n in range(3):  # old rows still read, and the blind-index lookup still finds them under the old key
        assert (await authed_client.get("/customers", params={"email": f"rot.{n}@example.com"})).json()["total"] == 1

    write_keys(regulated_keys, key_line("k3", 3))  # the old keys leave the ring BEFORE re-encrypting
    async with session_factory() as session:
        with pytest.raises(RegulatedError, match="nothing was changed") as exc:
            await reencrypt_all(session)
    assert "rot." not in str(exc.value)
    assert {r[0].split(":")[1] for r in await _raw("SELECT email FROM customers")} == {"k2", "k3"}  # untouched

    write_keys(regulated_keys, key_line("k3", 3), key_line("k2", 2), key_line("k1", 1))
    done = subprocess.run(  # the documented command
        [sys.executable, "-m", "app.regulated.reencrypt"], env=dict(os.environ), capture_output=True, text=True, timeout=300
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "customers.email: 3 re-encrypted" in done.stdout and "regulated_tokens.ciphertext: 3 re-encrypted" in done.stdout
    assert {r[0].split(":")[1] for r in await _raw("SELECT email FROM customers")} == {"k3"}
    assert {r[0].split(":")[1] for r in await _raw("SELECT ciphertext FROM regulated_tokens")} == {"k3"}
    async with session_factory() as session:  # idempotent
        assert set((await reencrypt_all(session)).values()) == {0}

    write_keys(regulated_keys, key_line("k3", 3))  # now the old keys can go
    for n in range(3):
        assert (await authed_client.get("/customers", params={"email": f"rot.{n}@example.com"})).json()["total"] == 1
        assert (await authed_client.get(f"/customers/{ids[n]}")).json()["email"] == f"rot.{n}@example.com"
    async with session_factory() as session:
        token = (await _raw("SELECT api_token FROM customers WHERE id = :i", i=uuid.UUID(ids[0])))[0][0]
        assert await tokens.detokenise(session, token) == "ROTTOKEN-0-aaaa-bbbb"


async def test_provider_vault_rides_the_keyring_without_provider_vault_key(
    authed_client: AsyncClient,  # noqa: F811
    regulated_keys: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("PROVIDER_VAULT_KEY", "PROVIDER_VAULT_KEY_VERSION", "PROVIDER_VAULT_KEY_PREVIOUS"):
        monkeypatch.delenv(name, raising=False)
    secret = "smtp-secret-VAULTMARKER-424242"
    put = await authed_client.put("/providers/credentials/acme_mail/api_key", json={"value": secret})
    assert put.status_code == 200, put.text
    [(tenant, ciphertext, version)] = await _raw("SELECT tenant_id, ciphertext, key_version FROM provider_credentials")
    assert secret not in ciphertext and version == keys.vault_version("k2")

    write_keys(regulated_keys, key_line("k3", 3), key_line("k2", 2))  # ring rotated: the credential stays readable
    async with session_factory() as session:
        assert (await vault.load(session, tenant, "acme_mail")).get("api_key") == secret
        assert await vault.reencrypt_all(session) == 1
        await session.commit()
    assert (await _raw("SELECT key_version FROM provider_credentials"))[0][0] == keys.vault_version("k3")

    write_keys(regulated_keys, key_line("k3", 3))
    async with session_factory() as session:
        assert (await vault.load(session, tenant, "acme_mail")).get("api_key") == secret


async def test_a_protected_value_is_in_no_table_and_no_log_line(
    authed_client: AsyncClient,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
    capfd: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.DEBUG)
    created = await _create(authed_client)
    await authed_client.patch(f"/customers/{created['id']}", json={"name": "Renamed"})
    await authed_client.get("/customers", params={"email": EMAIL})
    await authed_client.get(f"/customers/{created['id']}")
    refused = await authed_client.post("/customers", json={"name": "x" * 500, "email": EMAIL, "api_token": TOKEN_VALUE})
    assert refused.status_code == 422
    order = await authed_client.post("/orders", json={"reference": "R-1", "total": "10.00", "status": "new", "customer_id": created["id"]})
    assert order.status_code in (201, 422), order.text

    # the whole database, row by row (each row as text), must not hold either marker; the scan must not be vacuous
    tables = [r[0] for r in await _raw("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'")]
    assert {"customers", "ev_outbox", "ch_changes", "jb_jobs", "wh_deliveries", "regulated_tokens"} <= set(tables)
    assert (await _raw("SELECT count(*) FROM ev_outbox"))[0][0] >= 1  # the create event exists ...
    seen = 0
    for table in tables:
        for (row,) in await _raw(f'SELECT t::text FROM "{table}" t'):
            seen += 1
            assert EMAIL not in row and TOKEN_VALUE not in row, f"plaintext in {table}"
    assert seen > 5
    [(outbox_payload,)] = await _raw("SELECT payload::text FROM ev_outbox WHERE payload::text LIKE '%name%' LIMIT 1")
    assert "email" not in outbox_payload and "api_token" not in outbox_payload  # ... without the protected fields

    captured = capfd.readouterr()
    assert EMAIL not in caplog.text and TOKEN_VALUE not in caplog.text
    assert EMAIL not in captured.out + captured.err and TOKEN_VALUE not in captured.out + captured.err


def test_encryption_binds_the_column() -> None:
    stored = crypto.encrypt("customers", "email", "someone@example.com")
    with pytest.raises(RegulatedError):
        crypto.decrypt("customers", "api_token", stored)
