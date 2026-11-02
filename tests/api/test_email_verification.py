"""CO3-7 (F-5 + F-9): verified e-mail sign-up for platform accounts."""

import statistics
import time
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.platform import EmailVerificationToken, PlatformUser
from app.services import mail_service
from tests.api.conftest import ClientFor, MakeUser

Factory = async_sessionmaker[AsyncSession]
GOOD = "purple-giraffe-eats-lunch"


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """(recipient, raw token) of every verification mail; nothing is really sent."""
    box: list[tuple[str, str]] = []

    async def fake(*, to: str, url: str, hours: int) -> bool:
        box.append((to, url.split("token=", 1)[1]))
        return True

    monkeypatch.setattr(mail_service, "send_verification", fake)
    return box


async def _signup(c: AsyncClient, email: str):  # noqa: ANN202
    return await c.post("/account/register", json={"email": email, "password": GOOD, "name": "N"})


async def _verify(c: AsyncClient, token: str):  # noqa: ANN202
    return await c.post("/account/verify-email", json={"token": token})


async def _user(f: Factory, email: str) -> PlatformUser:
    async with f() as s:
        return (await s.execute(select(PlatformUser).where(PlatformUser.email == email))).scalar_one()


async def test_new_and_existing_addresses_get_the_same_answer(
    anon_client: AsyncClient, make_user: MakeUser, outbox: list[tuple[str, str]]
) -> None:
    await make_user("taken@example.com")
    new = await _signup(anon_client, "fresh@example.com")
    old = await _signup(anon_client, "taken@example.com")
    assert new.status_code == old.status_code == 202
    assert new.json() == old.json()
    assert new.headers.get("set-cookie") == old.headers.get("set-cookie") is None
    assert [to for to, _ in outbox] == ["fresh@example.com"]  # nothing goes to the old account


async def test_signup_timing_does_not_reveal_existing_accounts(
    anon_client: AsyncClient, make_user: MakeUser, outbox: list[tuple[str, str]]
) -> None:
    await make_user("taken2@example.com")

    async def timed(email: str) -> float:
        t = time.perf_counter()
        assert (await _signup(anon_client, email)).status_code == 202
        return time.perf_counter() - t

    new = [await timed(f"n{i}@example.com") for i in range(3)]
    old = [await timed("taken2@example.com") for _ in range(3)]
    ratio = statistics.median(new) / statistics.median(old)
    assert 0.33 < ratio < 3, (new, old)  # both spend one password hash


async def test_validation_errors_do_not_depend_on_the_account(
    anon_client: AsyncClient, make_user: MakeUser
) -> None:
    await make_user("taken3@example.com")
    for email in ("taken3@example.com", "nobody3@example.com"):
        r = await anon_client.post(
            "/account/register", json={"email": email, "password": "short", "name": "N"}
        )
        assert r.status_code == 422 and r.json()["code"] == "weak_password"


async def test_token_is_hashed_at_rest_and_verifies_once(
    anon_client: AsyncClient, session_factory: Factory, outbox: list[tuple[str, str]]
) -> None:
    await _signup(anon_client, "v@example.com")
    (_, token), = outbox
    assert (await _user(session_factory, "v@example.com")).email_verified_at is None
    async with session_factory() as s:
        row = (await s.execute(select(EmailVerificationToken))).scalar_one()
    assert token not in (row.token_hash, str(row.id)) and len(row.token_hash) == 64

    ok = await _verify(anon_client, token)
    assert ok.status_code == 200 and ok.json()["email_verified_at"] is not None
    assert (await _user(session_factory, "v@example.com")).email_verified_at is not None
    replay = await _verify(anon_client, token)  # replayed
    assert replay.status_code == 400 and replay.json()["code"] == "invalid_verification_token"


async def test_expired_and_unknown_tokens_get_the_same_error(
    anon_client: AsyncClient, session_factory: Factory, outbox: list[tuple[str, str]]
) -> None:
    await _signup(anon_client, "e@example.com")
    (_, token), = outbox
    async with session_factory() as s:
        await s.execute(
            update(EmailVerificationToken).values(expires_at=datetime.now(UTC) - timedelta(1))
        )
        await s.commit()
    expired = await _verify(anon_client, token)
    unknown = await _verify(anon_client, "bb_ev_" + "x" * 43)
    assert expired.status_code == unknown.status_code == 400
    assert expired.json() == unknown.json()
    assert (await _user(session_factory, "e@example.com")).email_verified_at is None


async def test_a_token_only_verifies_its_own_account(
    anon_client: AsyncClient, session_factory: Factory, outbox: list[tuple[str, str]]
) -> None:
    await _signup(anon_client, "a@example.com")
    await _signup(anon_client, "b@example.com")
    tokens = {to: t for to, t in outbox}
    assert (await _verify(anon_client, tokens["a@example.com"])).status_code == 200
    assert (await _user(session_factory, "a@example.com")).email_verified_at is not None
    assert (await _user(session_factory, "b@example.com")).email_verified_at is None
    # b's token still works for b only
    assert (await _verify(anon_client, tokens["b@example.com"])).json()["email"] == "b@example.com"


async def test_resend_is_generic_cooldown_limited_and_invalidates_the_old_link(
    anon_client: AsyncClient, session_factory: Factory, outbox: list[tuple[str, str]]
) -> None:
    await _signup(anon_client, "r@example.com")
    first = outbox[0][1]
    again = "/account/verify-email/resend"
    body = {"email": "r@example.com"}
    r1 = await anon_client.post(again, json=body)
    assert r1.status_code == 202 and len(outbox) == 1  # inside the cooldown: no second mail
    ghost = await anon_client.post(again, json={"email": "ghost@example.com"})
    assert ghost.json() == r1.json() and len(outbox) == 1
    async with session_factory() as s:
        await s.execute(
            update(EmailVerificationToken).values(created_at=datetime.now(UTC) - timedelta(1))
        )
        await s.commit()
    await anon_client.post(again, json=body)
    assert len(outbox) == 2
    assert (await _verify(anon_client, first)).status_code == 400  # superseded
    assert (await _verify(anon_client, outbox[1][1])).status_code == 200
    await anon_client.post(again, json=body)  # verified now: silently nothing
    assert len(outbox) == 2


async def test_unverified_accounts_cannot_generate_until_verified(
    anon_client: AsyncClient, client_for: ClientFor, outbox: list[tuple[str, str]]
) -> None:
    c = await client_for("u@example.com", email_verified_at=None)
    project = (await c.post("/projects", json={"name": "Shop"})).json()["id"]
    for path in ("generate/preview", "generate/download"):
        method = c.post if path.endswith("preview") else c.get
        r = await method(f"/projects/{project}/{path}")
        assert r.status_code == 403 and r.json()["code"] == "email_not_verified", path
    # reading and editing stays open
    assert (await c.get(f"/projects/{project}")).status_code == 200
    # a verified account is not blocked by the gate
    v = await client_for("w@example.com")
    pid = (await v.post("/projects", json={"name": "Ok"})).json()["id"]
    assert (await v.post(f"/projects/{pid}/generate/preview")).status_code != 403


async def test_no_token_in_the_response_or_the_logs(
    anon_client: AsyncClient, outbox: list[tuple[str, str]], capfd: pytest.CaptureFixture[str]
) -> None:
    r = await _signup(anon_client, "log@example.com")
    (_, token), = outbox
    out = capfd.readouterr()
    assert token not in r.text and token not in out.out and token not in out.err
