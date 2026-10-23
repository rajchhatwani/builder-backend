"""Helpers shared by the auth tests and the entity tests (generated).

No Keycloak is needed to run the tests: they sign tokens with a throwaway RSA key and make the
app fetch that key's public half instead of Keycloak's. Everything else (issuer, audience,
roles, expiry) goes through the same checks as in production.
"""

import base64
import json
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from httpx import ASGITransport, AsyncClient

from app.auth import config, oidc
from app.main import app

EMAIL = "ann@example.com"
ALL_ROLES: tuple[str, ...] = ('admin', 'editor', 'member')
KID = "test-key-1"

_TEST_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def other_key() -> rsa.RSAPrivateKey:
    """A signing key that is not the one the app trusts, for forging tokens."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _json(value: dict[str, Any]) -> str:
    return _b64(json.dumps(value, separators=(",", ":")).encode("utf-8"))


def issuer() -> str:
    return config.get_auth_settings().issuer


def claims(
    sub: uuid.UUID | str | None = None,
    *,
    email: str | None = EMAIL,
    roles: list[str] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """The claims of a valid Keycloak access token; `overrides` replace or (with None) drop."""
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": issuer(),
        "aud": [config.API_CLIENT_ID, "account"],
        "sub": str(sub or uuid.uuid5(uuid.NAMESPACE_URL, email or "nobody")),
        "typ": "Bearer",
        "azp": config.WEB_CLIENT_ID,
        "iat": now,
        "exp": now + 300,
        "email": email,
        "email_verified": True,
        "name": "Test User",
        "resource_access": {config.API_CLIENT_ID: {"roles": list(roles or [])}},
    }
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not None}


def sign(
    payload: dict[str, Any],
    *,
    key: rsa.RSAPrivateKey | None = None,
    header: dict[str, Any] | None = None,
) -> str:
    head: dict[str, Any] = {"alg": "RS256", "typ": "JWT", "kid": KID}
    head.update(header or {})
    head = {k: v for k, v in head.items() if v is not None}
    signing_input = f"{_json(head)}.{_json(payload)}"
    signature = (key or _TEST_KEY).sign(
        signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256()
    )
    return f"{signing_input}.{_b64(signature)}"


def token(email: str = EMAIL, roles: list[str] | None = None, **overrides: Any) -> str:
    return sign(claims(email=email, roles=roles, **overrides))


def public_pem() -> bytes:
    return _TEST_KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


class KeyServer:
    """Stands in for Keycloak's key endpoint: counts requests and can be switched off."""

    def __init__(self) -> None:
        self.keys: dict[str, rsa.RSAPublicKey] = {KID: _TEST_KEY.public_key()}
        self.calls = 0
        self.down = False

    def fetch(self, url: str) -> dict[str, rsa.RSAPublicKey]:
        self.calls += 1
        assert url == config.get_auth_settings().jwks_url
        if self.down:
            raise OSError("keycloak is down")
        return dict(self.keys)


def _install(monkeypatch: pytest.MonkeyPatch) -> Iterator[KeyServer]:
    """Test settings, a fake Keycloak key endpoint, and a clean key cache."""
    monkeypatch.setenv("KEYCLOAK_PUBLIC_URL", "https://id.test")
    monkeypatch.delenv("KEYCLOAK_INTERNAL_URL", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("AUTH_ALLOW_PROVIDER_SWITCH", raising=False)
    config.get_auth_settings.cache_clear()
    server = KeyServer()
    monkeypatch.setattr(oidc, "_fetch_jwks", server.fetch)
    oidc.reset_key_cache()
    yield server
    oidc.reset_key_cache()
    config.get_auth_settings.cache_clear()


@pytest.fixture
def key_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[KeyServer]:
    yield from _install(monkeypatch)


# The entity tests and test_access.py ask for this fixture by its built-in-auth name; it is
# the one tests/conftest.py exposes to every test module.
@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> Iterator[KeyServer]:
    yield from _install(monkeypatch)


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
    """The Authorization header of a user who holds `roles` (and the default roles).
    The profile row is created by the first request, exactly as in production."""
    del http, n, join  # accepted so tests written for built-in auth also run here
    return bearer(token(email=email, roles=list(roles or [])))


async def sign_in_plain(http: AsyncClient, email: str, **kwargs: object) -> dict[str, str]:
    """A user who holds only the default roles."""
    return await sign_in(http, email, roles=list(config.DEFAULT_ROLES), **kwargs)  # type: ignore[arg-type]


@pytest.fixture
async def authed_client(outbox: KeyServer) -> AsyncIterator[AsyncClient]:
    """A client signed in as a verified user who holds every role."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        http.headers.update(await sign_in(http, "all-roles@example.com", roles=list(ALL_ROLES)))
        yield http
