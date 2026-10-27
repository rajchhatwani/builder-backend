# ruff: noqa: F811
"""Follow-ups from the code review of the review fixes: SCIM seats and e-mail, org deletion
cleanup, the outbound-URL pin, TOTP attempt limits, mail headers, the SCIM limiter, the deletion
job and DNS errors."""

import smtplib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from dns.exception import FormError
from dns.resolver import YXDOMAIN
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api import security
from app.models.enums import OrgRole
from app.models.platform import Organization, OrganizationMember, PlatformUser
from app.models.scim import ScimDirectory
from app.models.sso import SsoDomain
from app.services import dns_txt, mail_service, oidc, org_deletion_service
from app.services.billing_service import BillingService
from tests.api._mfa_helpers import enroll
from tests.api.conftest import TEST_PASSWORD, TotpClock
from tests.api.test_scim import (
    SCIM,
    dns,  # noqa: F401 — the fixture
    enterprise_org,
    ops,
    provision,
    scim_token,
)
from tests.api.test_sso_config import verified_domain

Factory = async_sessionmaker[AsyncSession]


# -- SCIM offboarding frees the Stripe seat ------------------------------------------------------


@pytest.fixture
def synced(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    calls: list[uuid.UUID] = []

    async def fake(self: BillingService, organization_id: uuid.UUID, **_: object) -> None:
        calls.append(organization_id)

    monkeypatch.setattr(BillingService, "sync_seats", fake)
    return calls


@pytest.mark.usefixtures("dns")
async def test_scim_deactivate_and_delete_sync_the_seat_count(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
    synced: list[uuid.UUID],
) -> None:
    org = await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    first = (await provision(anon_client, h, "a@acme.test"))["id"]
    second = (await provision(anon_client, h, "b@acme.test"))["id"]
    synced.clear()
    r = await anon_client.patch(
        f"/scim/v2/Users/{first}",
        json=ops({"op": "replace", "path": "active", "value": False}),
        headers=h,
    )
    assert r.status_code == 200
    assert synced == [uuid.UUID(org)]
    synced.clear()
    assert (await anon_client.delete(f"{SCIM}/Users/{second}", headers=h)).status_code == 204
    assert synced == [uuid.UUID(org)]


# -- a deleted org lets go of its domain and directory -------------------------------------------


@pytest.mark.usefixtures("dns")
async def test_deleting_an_org_releases_its_domain_and_directory(
    client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    org = await enterprise_org(client, session_factory, dns)
    await scim_token(client)
    async with session_factory() as s:
        assert (await s.execute(select(SsoDomain))).first() is not None
        assert (await s.execute(select(ScimDirectory))).first() is not None
        await org_deletion_service.execute(s, uuid.UUID(org))
    async with session_factory() as s:
        assert (await s.execute(select(SsoDomain))).first() is None
        assert (await s.execute(select(ScimDirectory))).first() is None
    # The domain can be claimed again by a new org.
    again = (await client.post("/orgs", json={"name": "Next", "slug": "next"})).json()["id"]
    from tests.api.test_sso_config import set_plan

    await set_plan(session_factory, again, "enterprise")
    await verified_domain(client, dns, "acme.test", "next")


# -- SCIM won't rewrite an e-mail other orgs rely on ---------------------------------------------


@pytest.mark.usefixtures("dns")
async def test_scim_cannot_change_the_email_of_an_account_in_other_orgs(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
) -> None:
    await enterprise_org(client, session_factory, dns)
    h = await scim_token(client)
    uid = (await provision(anon_client, h))["id"]
    async with session_factory() as s:
        user = (
            await s.execute(select(PlatformUser).where(PlatformUser.email == "alice@acme.test"))
        ).scalar_one()
        other = Organization(name="Elsewhere", slug="elsewhere")
        s.add(other)
        await s.flush()
        s.add(OrganizationMember(organization_id=other.id, user_id=user.id, role=OrgRole.member))
        await s.commit()
    r = await anon_client.patch(
        f"{SCIM}/Users/{uid}",
        json=ops({"op": "replace", "path": "userName", "value": "al@acme.test"}),
        headers=h,
    )
    assert r.status_code == 409 and r.json()["scimType"] == "mutability"
    async with session_factory() as s:
        assert (
            await s.execute(select(PlatformUser).where(PlatformUser.email == "alice@acme.test"))
        ).scalar_one_or_none()


# -- the outbound fetch connects to the address it checked ---------------------------------------


async def test_outbound_fetch_is_pinned_to_the_checked_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = iter([["93.184.216.34"], ["10.0.0.5"]])  # DNS rebinding: public, then private
    lookups: list[str] = []

    async def resolve(host: str) -> list[str]:
        lookups.append(host)
        return next(answers)

    seen: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **_: object) -> None: ...

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *_: object) -> None: ...

        async def request(self, method: str, url: str, **kw: object) -> object:
            seen.update(url=url, **kw)
            return SimpleNamespace(content=b"{}")

    monkeypatch.setattr(oidc, "_resolve", resolve)
    monkeypatch.setattr(oidc.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(oidc, "TRANSPORT", None)
    await oidc._request(  # noqa: SLF001
        "GET",
        "https://idp.example/.well-known/openid-configuration",
        allow_private=False,
        require_https=True,
    )
    assert lookups == ["idp.example"]  # resolved once, so a second answer can't matter
    assert seen["url"] == "https://93.184.216.34/.well-known/openid-configuration"
    assert seen["headers"] == {"Host": "idp.example"}
    assert seen["extensions"] == {"sni_hostname": "idp.example"}


# -- TOTP codes from a signed-in session are attempt-limited -------------------------------------


async def test_signed_in_code_guessing_locks_the_account(
    client: AsyncClient, totp_clock: TotpClock
) -> None:
    secret, _ = await enroll(client, totp_clock)
    last = 0
    for _ in range(5):
        r = await client.post("/account/mfa/recovery-codes", json={"code": "000000"})
        last = r.status_code
        assert last == 422
    # Locked: even the right code is refused now.
    r = await client.post("/account/mfa/recovery-codes", json={"code": totp_clock.code(secret)})
    assert r.status_code == 429 and r.json()["code"] == "too_many_attempts"


async def test_wrong_enable_codes_count_too(client: AsyncClient) -> None:

    await client.post("/account/mfa/totp/setup", json={"password": TEST_PASSWORD})
    codes = [
        (await client.post("/account/mfa/totp/enable", json={"code": "000000"})).status_code
        for _ in range(6)
    ]
    assert codes[:5] == [422] * 5 and codes[5] == 429


# -- a newline in an org name can't break the invitation e-mail ---------------------------------


def test_mail_headers_survive_newlines(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[object] = []

    class FakeSmtp:
        def __init__(self, *a: object, **k: object) -> None: ...
        def __enter__(self) -> "FakeSmtp":
            return self

        def __exit__(self, *_: object) -> None: ...
        def send_message(self, message: object) -> None:
            sent.append(message)

    settings = SimpleNamespace(
        smtp_host="smtp.test",
        smtp_port=25,
        smtp_from="b@x.test",
        smtp_starttls=False,
        smtp_username=None,
        smtp_password=None,
    )
    monkeypatch.setattr(mail_service, "get_settings", lambda: settings)
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    mail_service._send_sync("a@b.test", "You're invited to Evil\nBcc: x@y.test", "hi")  # noqa: SLF001
    assert len(sent) == 1
    assert "\n" not in str(sent[0]["Subject"])  # type: ignore[index]
    assert sent[0]["Bcc"] is None  # type: ignore[index]


async def test_a_header_error_is_a_failed_send_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mail_service, "mail_configured", lambda: True)

    def boom(*_: object) -> None:
        raise ValueError("header")

    monkeypatch.setattr(mail_service, "_send_sync", boom)
    assert await mail_service.send("a@b.test", "s", "b") is False


# -- the SCIM failure limiter blocks before authenticating ---------------------------------------


async def test_scim_blocks_a_noisy_address_before_checking_the_token(
    client: AsyncClient,
    anon_client: AsyncClient,
    session_factory: Factory,
    dns: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await enterprise_org(client, session_factory, dns)
    good = await scim_token(client)
    limiter = security.auth_limiter()
    bad = {"Authorization": "Bearer scim_" + "x" * 40}
    for _ in range(limiter.attempts):
        assert (await anon_client.get(f"{SCIM}/Users", headers=bad)).status_code == 401
    # The address is now over its limit: even the right token waits.
    assert (await anon_client.get(f"{SCIM}/Users", headers=good)).status_code == 429


# -- the deletion job -----------------------------------------------------------------------------


async def test_one_failing_org_does_not_stop_the_deletion_job(
    client: AsyncClient, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = []
    for slug in ("one", "two"):
        ids.append((await client.post("/orgs", json={"name": slug, "slug": slug})).json()["id"])
    async with session_factory() as s:
        for org_id in ids:
            row = await s.get(Organization, uuid.UUID(org_id))
            assert row is not None
            row.deletion_requested_at = datetime.now(UTC) - timedelta(days=8)
            row.deletion_scheduled_for = datetime.now(UTC) - timedelta(minutes=1)
        await s.commit()
    real = org_deletion_service.execute
    failing = uuid.UUID(ids[0])

    async def flaky(session: AsyncSession, organization_id: uuid.UUID, **kw: object) -> int:
        if organization_id == failing:
            raise RuntimeError("boom")
        return await real(session, organization_id, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(org_deletion_service, "execute", flaky)
    async with session_factory() as s:
        assert await org_deletion_service.run_due(s) == 1
    async with session_factory() as s:
        first = await s.get(Organization, uuid.UUID(ids[0]))
        second = await s.get(Organization, uuid.UUID(ids[1]))
        assert first is not None and second is not None
        assert first.deleted_at is None and second.deleted_at is not None


async def test_the_job_skips_an_org_that_took_a_subscription_since_the_request(
    client: AsyncClient, session_factory: Factory
) -> None:
    from app.models.platform import Subscription

    org = (await client.post("/orgs", json={"name": "Paid", "slug": "paid"})).json()["id"]
    async with session_factory() as s:
        row = await s.get(Organization, uuid.UUID(org))
        assert row is not None
        row.deletion_requested_at = datetime.now(UTC) - timedelta(days=8)
        row.deletion_scheduled_for = datetime.now(UTC) - timedelta(minutes=1)
        sub = await s.get(Subscription, uuid.UUID(org))
        assert sub is not None
        sub.stripe_customer_id, sub.stripe_subscription_id = "cus_1", "sub_1"
        await s.commit()
    async with session_factory() as s:
        assert await org_deletion_service.run_due(s) == 0
    async with session_factory() as s:
        row = await s.get(Organization, uuid.UUID(org))
        assert row is not None and row.deleted_at is None


# -- DNS errors are "not found", not a 500 -------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [YXDOMAIN(), FormError(), UnicodeError("bad label")],
)
async def test_odd_dns_failures_mean_no_records(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    class Boom:
        lifetime = 0.0

        async def resolve(self, *_: object) -> None:
            raise error

    monkeypatch.setattr(dns_txt.dns.asyncresolver, "Resolver", Boom)
    assert await dns_txt.txt_records("_builder.acme.test") == []
