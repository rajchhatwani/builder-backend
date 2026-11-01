"""Provider checks (generated): the credential vault, the emulator, retries, the breaker, and that no
secret reaches a log, an error or a response."""

import json
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from pydantic import BaseModel
from structlog.testing import capture_logs

from app.db import session_factory
from app.providers import breaker, config, definitions, logsafe, registry, schemas, vault
from app.providers import client as provider_client
from app.providers.base import Credentials
from app.providers.errors import (
    AuthFailed,
    CircuitOpen,
    NotConfigured,
    Permanent,
    ProviderTimeout,
    RateLimited,
    Retryable,
    VaultError,
)
from app.providers.models import ProviderCredential
from app.providers.schemas import EmailRequest, HealthStatus, SendResult
from tests._auth_support import outbox, sign_in, sign_in_plain  # noqa: F401
from tests._providers_support import KEY_1, KEY_2, emulator, vault_env  # noqa: F401

ADMIN = 'admin'
CANARY = "CANARY-7f3a91c4e8d2b6051a9e3c7f-do-not-leak"
MAIL = EmailRequest(to="ann@example.com", subject="Hello", body="A body that must never be logged")
TENANT = uuid.UUID("11111111-1111-4111-8111-111111111111")
OTHER_TENANT = uuid.UUID("22222222-2222-4222-8222-222222222222")


def _all_text(*parts: object) -> str:
    return "\n".join(str(p) for p in parts)


def _no_canary(*parts: object) -> None:
    assert CANARY not in _all_text(*parts)


async def _rows() -> list[ProviderCredential]:
    async with session_factory() as session:
        return list((await session.execute(sa.select(ProviderCredential))).scalars())


def test_credentials_object_hides_its_values() -> None:
    creds = Credentials({"api_key": CANARY})
    _no_canary(repr(creds), str(creds), f"{creds}", creds.names())
    assert creds.get("api_key") == CANARY
    with pytest.raises(TypeError):
        import pickle

        pickle.dumps(creds)


def test_the_router_never_decrypts() -> None:
    source = (Path(provider_client.__file__).parent / "router.py").read_text(encoding="utf-8")
    assert "decrypt(" not in source and "vault.load" not in source and "get_secret_value()" in source


@pytest.mark.parametrize("problem", ["missing", "short", "placeholder", "repetitive"])
def test_production_refuses_a_bad_master_key(monkeypatch: pytest.MonkeyPatch, problem: str) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    bad = {"short": "too-short", "placeholder": "changeme-" + "ab12cd34" * 4, "repetitive": "a" * 40}
    if problem == "missing":
        monkeypatch.delenv("PROVIDER_VAULT_KEY", raising=False)
    else:
        monkeypatch.setenv("PROVIDER_VAULT_KEY", bad[problem])
    with pytest.raises(VaultError) as raised:
        config.check_boot()
    _no_canary(raised.value)
    assert bad.get(problem, "\0") not in str(raised.value)
    monkeypatch.setenv("APP_ENV", "development")
    config.check_boot()  # outside production a missing key only fails when the vault is used
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PROVIDER_VAULT_KEY", KEY_1)
    config.check_boot()


@pytest.mark.parametrize(
    ("value", "production"),
    [
        ("prod", True), ("Production", True), (" production ", True), ("staging", True),
        (None, True), ("banana", True), ("", True),
        ("development", False), ("Local", False), (" test ", False), ("demo", False), ("preview", False),
    ],
)  # fmt: skip
def test_only_an_explicit_development_name_is_not_production(
    monkeypatch: pytest.MonkeyPatch, value: str | None, production: bool
) -> None:
    if value is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", value)
    assert config.is_production() is production
    monkeypatch.delenv("PROVIDER_VAULT_KEY", raising=False)
    if production:
        with pytest.raises(VaultError):
            config.check_boot()  # the key check is enforced
    else:
        config.check_boot()


URL = "/providers/credentials/acme_mail/api_key"


async def test_an_admin_stores_lists_and_deletes_a_credential_but_never_reads_it_back(
    client: AsyncClient, outbox, vault_env  # noqa: ANN001, F811
) -> None:
    admin = await sign_in(client, "admin@example.com", roles=[ADMIN])
    put = await client.put(URL, json={"value": CANARY}, headers=admin)
    assert put.status_code == 200, put.text
    body = put.json()
    assert set(body) == {"provider", "key_name", "fingerprint", "key_version", "created_at", "rotated_at"}
    assert body["provider"] == "acme_mail" and body["key_name"] == "api_key" and body["key_version"] == 1
    listing = await client.get("/providers/credentials", headers=admin)
    assert [(c["provider"], c["key_name"]) for c in listing.json()] == [("acme_mail", "api_key")]
    _no_canary(put.text, listing.text)
    rows = await _rows()
    assert len(rows) == 1 and CANARY not in rows[0].ciphertext and CANARY not in rows[0].fingerprint
    again = await client.put(URL, json={"value": CANARY + "-2"}, headers=admin)
    assert again.json()["fingerprint"] != body["fingerprint"] and again.json()["rotated_at"] is not None
    assert (await client.delete(URL, headers=admin)).status_code == 204
    assert (await client.get("/providers/credentials", headers=admin)).json() == []
    assert (await client.delete(URL, headers=admin)).status_code == 404


async def test_only_the_admin_role_may_use_the_vault(
    client: AsyncClient, outbox, vault_env  # noqa: ANN001, F811
) -> None:
    plain = await sign_in_plain(client, "plain@example.com")
    for headers in (plain, {}):
        expected = 403 if headers else 401
        assert (await client.put(URL, json={"value": CANARY}, headers=headers)).status_code == expected
        assert (await client.get("/providers/credentials", headers=headers)).status_code == expected
        assert (await client.delete(URL, headers=headers)).status_code == expected
        assert (await client.get("/providers/health/email", headers=headers)).status_code == expected
    assert await _rows() == []


async def test_bad_input_is_refused_without_echoing_the_secret(
    client: AsyncClient, outbox, vault_env  # noqa: ANN001, F811
) -> None:
    admin = await sign_in(client, "admin@example.com", roles=[ADMIN])
    too_long = await client.put(URL, json={"value": CANARY * 400}, headers=admin)
    extra = await client.put(URL, json={"value": "x", CANARY: CANARY}, headers=admin)
    empty = await client.put(URL, json={"value": ""}, headers=admin)
    unknown = await client.put("/providers/credentials/nobody/api_key", json={"value": CANARY}, headers=admin)
    badname = await client.put("/providers/credentials/acme_mail/Bad-Name", json={"value": CANARY}, headers=admin)
    assert [r.status_code for r in (too_long, empty, unknown, badname)] == [422, 422, 404, 422]
    assert extra.status_code == 422
    for response in (too_long, empty, unknown, badname):
        _no_canary(response.text)
    assert CANARY not in too_long.text and "CANARY" not in too_long.text
    assert await _rows() == []


async def test_without_a_master_key_the_vault_refuses_to_store(
    client: AsyncClient, outbox, vault_env  # noqa: ANN001, F811
) -> None:
    admin = await sign_in(client, "admin@example.com", roles=[ADMIN])
    vault_env.delenv("PROVIDER_VAULT_KEY")
    refused = await client.put(URL, json={"value": CANARY}, headers=admin)
    assert refused.status_code == 503 and refused.json()["code"] == "vault_unavailable"
    _no_canary(refused.text)
    assert await _rows() == []


async def test_a_tenant_never_sees_or_uses_another_tenants_credentials(
    client: AsyncClient, outbox, vault_env  # noqa: ANN001, F811
) -> None:
    first = await sign_in(client, "first@example.com", roles=[ADMIN])
    second = await sign_in(client, "second@example.com", roles=[ADMIN])
    assert (await client.put(URL, json={"value": CANARY}, headers=first)).status_code == 200
    assert (await client.get("/providers/credentials", headers=second)).json() == []
    assert (await client.delete(URL, headers=second)).status_code == 404
    assert len((await client.get("/providers/credentials", headers=first)).json()) == 1
    mine = await client.put(URL, json={"value": "second-tenants-own-secret-value"}, headers=second)
    assert mine.status_code == 200
    rows = {r.tenant_id: r for r in await _rows()}
    assert len(rows) == 2
    first_id, second_id = list(rows)
    async with session_factory() as session:
        for tenant_id in rows:
            loaded = await vault.load(session, tenant_id, "acme_mail")
            assert loaded.get("api_key") in (CANARY, "second-tenants-own-secret-value")
        assert (await vault.load(session, first_id, "acme_mail")).get("api_key") != (
            await vault.load(session, second_id, "acme_mail")
        ).get("api_key")
        # a ciphertext moved into another tenant's row does not open: the tenant is part of what is signed
        stolen = rows[first_id].ciphertext
        row = (await session.execute(sa.select(ProviderCredential).where(ProviderCredential.tenant_id == second_id))).scalar_one()
        row.ciphertext = stolen
        await session.flush()
        with pytest.raises(VaultError):
            await vault.load(session, second_id, "acme_mail")
        await session.rollback()


async def test_rotation_keeps_old_credentials_readable_until_they_are_re_encrypted(
    vault_env: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    async with session_factory() as session:
        await vault.put(session, TENANT, "acme_mail", "api_key", CANARY, None)
        await session.commit()
    vault_env.setenv("PROVIDER_VAULT_KEY", KEY_2)
    vault_env.setenv("PROVIDER_VAULT_KEY_VERSION", "2")
    vault_env.setenv("PROVIDER_VAULT_KEY_PREVIOUS", f"1={KEY_1}")
    async with session_factory() as session:
        assert (await vault.load(session, TENANT, "acme_mail")).get("api_key") == CANARY
        assert [r.key_version for r in await _rows()] == [1]
        assert await vault.reencrypt_all(session) == 1
        assert await vault.reencrypt_all(session) == 0
        await session.commit()
    assert [r.key_version for r in await _rows()] == [2]
    vault_env.delenv("PROVIDER_VAULT_KEY_PREVIOUS")  # the old key can be dropped now
    async with session_factory() as session:
        assert (await vault.load(session, TENANT, "acme_mail")).get("api_key") == CANARY
    # and a credential still on a dropped version is reported without naming any key
    async with session_factory() as session:
        await session.execute(sa.update(ProviderCredential).values(key_version=1))
        await session.commit()
        with pytest.raises(VaultError) as raised:
            await vault.load(session, TENANT, "acme_mail")
    _no_canary(raised.value)
    assert KEY_1 not in str(raised.value) and KEY_2 not in str(raised.value)


async def test_a_tampered_ciphertext_does_not_decrypt(vault_env: pytest.MonkeyPatch) -> None:  # noqa: F811
    async with session_factory() as session:
        await vault.put(session, TENANT, "acme_mail", "api_key", CANARY, None)
        row = (await session.execute(sa.select(ProviderCredential))).scalar_one()
        row.ciphertext = row.ciphertext[:-4] + ("AAAA" if not row.ciphertext.endswith("AAAA") else "BBBB")
        await session.flush()
        with pytest.raises(VaultError) as raised:
            await vault.load(session, TENANT, "acme_mail")
        _no_canary(raised.value)
        await session.rollback()


async def test_a_credential_changes_which_adapter_a_tenant_uses(
    emulator, vault_env: pytest.MonkeyPatch  # noqa: ANN001, F811
) -> None:
    seen: list[tuple[list[str], str]] = []

    class Real:
        kind = "email"
        name = "acme_mail"

        async def health(self, credentials: Credentials | None) -> HealthStatus:
            return HealthStatus(ok=True)

        async def call(self, request: BaseModel, credentials: Credentials | None) -> BaseModel:
            assert credentials is not None
            seen.append((credentials.names(), type(request).__name__))
            return SendResult(message_id="real-1")

    registry.registered("email")  # load the registry first
    vault_env.setitem(registry._FACTORIES, ("email", "acme_mail"), Real)
    async with session_factory() as session:
        await vault.put(session, TENANT, "acme_mail", "api_key", CANARY, None)
        await session.commit()
    request = schemas.EmailRequest(to="ann@example.com", subject="Hello", body="A body that must never be logged")
    async with session_factory() as session:
        # APP_ENV=test: the emulator even with credentials, so a test can never reach out
        result = await provider_client.call_provider(session, TENANT, "email", request)
        assert result.message_id.startswith("emu-") and seen == []
        with pytest.raises(NotConfigured):
            provider_client.assert_allowed(Real())
        # development with credentials: the tenant's own adapter, credentials decrypted for the call only
        vault_env.setenv("APP_ENV", "development")
        result = await provider_client.call_provider(session, TENANT, "email", request)
        assert result.message_id == "real-1" and seen == [(["api_key"], type(request).__name__)]
        # another tenant has no credentials: the emulator
        other = await provider_client.call_provider(session, OTHER_TENANT, "email", request)
        assert other.message_id.startswith("emu-")
        # production: no credentials means no provider, and the emulator never runs
        vault_env.setenv("APP_ENV", "production")
        with pytest.raises(NotConfigured):
            await provider_client.call_provider(session, OTHER_TENANT, "email", request)
        with pytest.raises(NotConfigured):
            provider_client.assert_allowed(registry.adapter("email", "emulator"))


async def test_no_secret_reaches_a_log_an_error_or_a_response(
    emulator, client: AsyncClient, outbox, vault_env: pytest.MonkeyPatch  # noqa: ANN001, F811
) -> None:
    admin = await sign_in(client, "admin@example.com", roles=[ADMIN])
    stored = await client.put(URL, json={"value": CANARY}, headers=admin)
    tenant = (await _rows())[0].tenant_id
    failures: list[BaseException] = []

    class Leaky:
        kind = "email"
        name = "acme_mail"
        mode = "retryable"

        async def health(self, credentials: Credentials | None) -> HealthStatus:
            return HealthStatus(ok=True)

        async def call(self, request: BaseModel, credentials: Credentials | None) -> BaseModel:
            assert credentials is not None
            secret = credentials.get("api_key")
            if self.mode == "retryable":
                raise Retryable(f"upstream said {secret}")
            if self.mode == "auth":
                raise AuthFailed(f"bad key {secret}")
            if self.mode == "limit":
                raise RateLimited(f"slow down {secret}", retry_after=1)
            if self.mode == "permanent":
                raise Permanent(f"refused {secret}")
            raise RuntimeError(f"boom {secret}")

    leaky = Leaky()
    registry.registered("email")
    vault_env.setitem(registry._FACTORIES, ("email", "acme_mail"), lambda: leaky)
    vault_env.setenv("APP_ENV", "development")
    request = schemas.EmailRequest(to="ann@example.com", subject="Hello", body="A body that must never be logged")
    shown: list[object] = [stored.text]
    with capture_logs() as logs:
        for mode in ("retryable", "auth", "limit", "permanent", "bug"):
            leaky.mode = mode
            breaker.reset_all()
            async with session_factory() as session:
                with pytest.raises(Exception) as raised:
                    await provider_client.call_provider(session, tenant, "email", request)
            failures.append(raised.value)
            shown += [raised.value, repr(raised.value), raised.value.__cause__, raised.value.__context__]
        logsafe.log("note", text=f"carrying {CANARY}", api_key=CANARY, nested={"authorization": CANARY})
        logsafe.warn("note", detail=[CANARY])
    assert logs, "calls must be logged"
    assert all(isinstance(e, (Retryable, AuthFailed, RateLimited, Permanent)) for e in failures)
    shown.append(json.dumps(logs, default=str))
    shown.append((await client.get("/providers/credentials", headers=admin)).text)
    shown.append((await client.get("/openapi.json")).text)
    shown.append((await client.get("/providers/health/email", headers=admin)).text)
    _no_canary(*shown)
    # what a call logs is its shape, never a body
    request_logs = [e for e in logs if e.get("event") == "provider_call"]
    assert request_logs and all(CANARY not in str(e) and "must never be logged" not in str(e) for e in request_logs)


async def test_the_emulator_receives_what_is_sent(emulator) -> None:  # noqa: ANN001, F811
    async with session_factory() as session:
        first = await provider_client.call_provider(session, TENANT, "email", MAIL)
        second = await provider_client.call_provider(session, TENANT, "email", MAIL)
    assert (first.message_id, second.message_id) == ("emu-email-000001", "emu-email-000002")
    assert [s.request["to"] for s in emulator.sent["email"]] == ["ann@example.com"] * 2
    assert emulator.sent["sms"] == []
    async with session_factory() as session:
        assert (await provider_client.check_health(session, TENANT, "email")).ok


async def test_retryable_failures_are_retried_and_permanent_ones_are_not(emulator) -> None:  # noqa: ANN001, F811
    emulator.inject("email", "retryable", times=2)
    async with session_factory() as session:
        result = await provider_client.call_provider(session, TENANT, "email", MAIL)
        assert result.message_id == "emu-email-000001" and emulator.calls["email"] == 3
        assert emulator.waits == [0.5, 1.0]  # type: ignore[attr-defined]
        emulator.inject("email", "permanent")
        with pytest.raises(Permanent):
            await provider_client.call_provider(session, TENANT, "email", MAIL)
        assert emulator.calls["email"] == 4
        emulator.inject("email", "auth")
        with pytest.raises(AuthFailed):
            await provider_client.call_provider(session, TENANT, "email", MAIL)
        assert emulator.calls["email"] == 5
        emulator.waits.clear()  # type: ignore[attr-defined]
        emulator.inject("email", "rate_limit", times=1, value=7.0)
        await provider_client.call_provider(session, TENANT, "email", MAIL)
        assert emulator.waits == [7.0]  # type: ignore[attr-defined]
        with pytest.raises(Permanent):
            await provider_client.call_provider(session, TENANT, "sms", MAIL)  # type: ignore[arg-type]


async def test_a_timeout_is_reported_and_retried(emulator, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001, F811
    monkeypatch.setattr(definitions, "TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(definitions, "MAX_ATTEMPTS", 2)
    emulator.inject("email", "timeout", times=2)
    async with session_factory() as session:
        with pytest.raises(ProviderTimeout):
            await provider_client.call_provider(session, TENANT, "email", MAIL)
    assert emulator.calls["email"] == 2


async def test_the_breaker_opens_after_failures_and_probes_before_closing(  # noqa: PLR0915
    emulator, monkeypatch: pytest.MonkeyPatch  # noqa: ANN001, F811
) -> None:
    monkeypatch.setattr(definitions, "MAX_ATTEMPTS", 1)
    monkeypatch.setattr(definitions, "BREAKER_FAILURES", 3)
    monkeypatch.setattr(definitions, "BREAKER_RESET_SECONDS", 30.0)
    now = [1000.0]
    monkeypatch.setattr(breaker.time, "monotonic", lambda: now[0])
    emulator.inject("email", "retryable", times=3)
    async with session_factory() as session:
        for _ in range(3):
            with pytest.raises(Retryable):
                await provider_client.call_provider(session, TENANT, "email", MAIL)
        calls = emulator.calls["email"]
        with pytest.raises(CircuitOpen):  # open: the adapter is not reached
            await provider_client.call_provider(session, TENANT, "email", MAIL)
        assert emulator.calls["email"] == calls
        # the breaker belongs to the tenant: another tenant is not affected
        assert (await provider_client.call_provider(session, OTHER_TENANT, "email", MAIL)).accepted
        now[0] += 31  # half-open: one probe; it fails, so it opens again
        emulator.inject("email", "retryable")
        with pytest.raises(Retryable):
            await provider_client.call_provider(session, TENANT, "email", MAIL)
        with pytest.raises(CircuitOpen):
            await provider_client.call_provider(session, TENANT, "email", MAIL)
        now[0] += 31  # half-open again: the probe succeeds and the breaker closes
        assert (await provider_client.call_provider(session, TENANT, "email", MAIL)).accepted
        assert (await provider_client.call_provider(session, TENANT, "email", MAIL)).accepted


def test_the_breaker_lets_only_one_probe_through_when_half_open() -> None:
    now = [0.0]
    b = breaker.CircuitBreaker(2, 10.0, clock=lambda: now[0])
    b.failure()
    b.failure()
    assert b.state == breaker.OPEN and not b.allow()
    now[0] = 11.0
    assert b.state == breaker.HALF_OPEN
    assert b.allow() and not b.allow()
    b.success()
    assert b.state == breaker.CLOSED and b.allow()


async def test_the_guard_runs_only_the_emulator_when_testing(emulator) -> None:  # noqa: ANN001, F811
    async with session_factory() as session:
        adapter, credentials = await provider_client.resolve(session, TENANT, "sms")
    assert adapter.name == "emulator" and credentials is None
    assert "emulator" in registry.registered("sms")
