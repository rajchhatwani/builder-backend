"""Helpers shared by the auth tests and the entity tests (generated)."""

import datetime as dt
import re
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.auth import config, security
from app.auth.delivery import get_mailer, get_sms_sender
from app.auth.models import AuthInvitation, AuthUser
from app.auth.ratelimit import reset_all
from app.auth.router import _login_limit, _register_limit, _reset_limit
from app.db import session_factory
from app.main import app

PASSWORD = "correct horse battery"
EMAIL = "ann@example.com"
ALL_ROLES: tuple[str, ...] = ('admin', 'customer', 'staff')
_TOKEN_RE = re.compile(r"token=([A-Za-z0-9._~%-]+)")
_CODE_RE = re.compile(r"\b([0-9]{6})\b")


def other_key() -> str:
    """A signing key that is not the app's, for forging tokens."""
    return "a-different-secret-" + "y" * 32


def extra(n: int = 0) -> dict[str, object]:
    """Values for the custom registration fields; `n` (0-9) keeps unique fields unique."""
    return {}


@dataclass
class Outbox:
    emails: list[tuple[str, str, str]] = field(default_factory=list)
    sms: list[tuple[str, str]] = field(default_factory=list)

    def link_token(self) -> str:
        match = _TOKEN_RE.search(self.emails[-1][2])
        assert match, self.emails[-1][2]
        return match.group(1)

    def sms_code(self) -> str:
        match = _CODE_RE.search(self.sms[-1][1])
        assert match, self.sms[-1][1]
        return match.group(1)


class _Mailer:
    def __init__(self, box: Outbox) -> None:
        self.box = box

    async def send(self, to: str, subject: str, body: str) -> None:
        self.box.emails.append((to, subject, body))


class _Sms:
    def __init__(self, box: Outbox) -> None:
        self.box = box

    async def send(self, to: str, body: str) -> None:
        self.box.sms.append((to, body))


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> Iterator[Outbox]:
    """Test secrets, no real email / SMS, and relaxed rate limits (each test signs in a lot)."""
    monkeypatch.setenv("AUTH_JWT_SECRET", "test-only-secret-" + "x" * 32)
    config.get_auth_settings.cache_clear()
    reset_all()
    for limiter in (_login_limit, _register_limit, _reset_limit):
        monkeypatch.setattr(limiter, "count", 10_000)
    box = Outbox()
    app.dependency_overrides[get_mailer] = lambda: _Mailer(box)
    app.dependency_overrides[get_sms_sender] = lambda: _Sms(box)
    yield box
    app.dependency_overrides.pop(get_mailer, None)
    app.dependency_overrides.pop(get_sms_sender, None)
    config.get_auth_settings.cache_clear()


async def invitation_token(
    email: str, roles: list[str] | None = None, *, join: str | None = None
) -> str:
    """Put an invitation for `email` straight into the database and return its token.
    With multi-tenancy `join` names an existing user whose tenant the invitation is for."""
    token = security.new_token()
    async with session_factory() as session:
        invitation = AuthInvitation(
            email=email,
            roles=roles or [],
            token_hash=security.hash_secret(token),
            expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(days=1),
        )
        session.add(invitation)
        await session.commit()
    return token


async def registration_payload(
    email: str, n: int = 0, *, join: str | None = None
) -> dict[str, object]:
    """A valid /auth/register body.

    Invite-only registration carries an invitation. With multi-tenancy the user creates a
    tenant of their own, or joins `join`'s tenant when that email is given."""
    payload: dict[str, object] = {"email": email, "password": PASSWORD, **extra(n)}
    return payload


def bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def client_for(headers: dict[str, str]) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers)


async def sign_in(
    http: AsyncClient,
    email: str,
    *,
    roles: list[str] | None = None,
    n: int = 0,
    join: str | None = None,
) -> dict[str, str]:
    """Register `email` through the API, then verify it (and optionally set its roles) straight
    in the database, log in and return the Authorization header."""
    response = await http.post(
        "/auth/register", json=await registration_payload(email, n, join=join)
    )
    assert response.status_code == 201, response.text
    async with session_factory() as session:
        user = (await session.execute(select(AuthUser).where(AuthUser.email == email))).scalar_one()
        user.email_verified_at = user.email_verified_at or user.created_at
        if roles is not None:
            user.roles = list(roles)
        await session.commit()
    login = await http.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return bearer(login.json()["access_token"])


async def sign_in_plain(http: AsyncClient, email: str, **kwargs: object) -> dict[str, str]:
    """A user who holds only the default roles (not even the admin a tenant founder gets)."""
    return await sign_in(http, email, roles=list(config.DEFAULT_ROLES), **kwargs)  # type: ignore[arg-type]


@pytest.fixture
async def authed_client(outbox: Outbox) -> AsyncIterator[AsyncClient]:
    """A client signed in as a verified user who holds every role."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        http.headers.update(await sign_in(http, "all-roles@example.com", roles=list(ALL_ROLES)))
        yield http
