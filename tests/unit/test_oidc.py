"""OIDC relying-party adapter (PLATFORM_SAAS_PLAN §4.2): discovery, PKCE, ID token checks, and
the outbound-URL guard (an org admin types the discovery URL; the server fetches it)."""

import base64
import hashlib
import json
import urllib.parse

import httpx
import jwt
import pytest

from app.services import oidc
from tests.sso_fake_idp import (
    OIDC_DISCOVERY_URL,
    OIDC_ISSUER,
    attacker_keys,
    discovery_document,
    id_token,
    idp_keys,
    jwks,
)

CLIENT = "builder-client"
NONCE = "n-0123456789"


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(host: str) -> list[str]:
        return {"internal.test": ["10.0.0.5"], "meta.test": ["169.254.169.254"]}.get(
            host, ["93.184.216.34"]
        )

    monkeypatch.setattr(oidc, "_resolve", resolve)


def _verify(token: str, **kw: object) -> oidc.OidcIdentity:
    args: dict[str, object] = {
        "jwks": jwks(),
        "issuer": OIDC_ISSUER,
        "client_id": CLIENT,
        "nonce": NONCE,
    }
    args.update(kw)
    return oidc.verify_id_token(token, **args)  # type: ignore[arg-type]


def _reason(token: str, **kw: object) -> str:
    with pytest.raises(oidc.OidcError) as err:
        _verify(token, **kw)
    return err.value.reason


# -- ID token ---------------------------------------------------------------------------------


def test_valid_id_token() -> None:
    ident = _verify(id_token(client_id=CLIENT, nonce=NONCE, email="Alice@Acme.test"))
    assert ident.email == "alice@acme.test"
    assert ident.name == "Alice Smith"
    assert ident.subject == "user-Alice@Acme.test"


def test_missing_email_verified_is_refused_by_default() -> None:
    token = id_token(client_id=CLIENT, nonce=NONCE, email="a@acme.test", email_verified=None)
    assert _reason(token) == "email_not_verified"


def test_missing_email_verified_is_accepted_when_the_org_trusts_its_idp() -> None:
    """Entra ID omits it; the connection's opt-in (and the verified-domain rule) gate it."""
    token = id_token(client_id=CLIENT, nonce=NONCE, email="a@acme.test", email_verified=None)
    assert _verify(token, trust_unverified_email=True).email == "a@acme.test"


def test_an_explicit_false_is_refused_even_when_trusted() -> None:
    token = id_token(client_id=CLIENT, nonce=NONCE, email="a@acme.test", email_verified=False)
    assert _reason(token, trust_unverified_email=True) == "email_not_verified"


def test_unverified_email_is_refused() -> None:
    token = id_token(client_id=CLIENT, nonce=NONCE, email="a@acme.test", email_verified=False)
    assert _reason(token) == "email_not_verified"


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"issuer": "https://evil.test"}, "bad_id_token"),
        ({"audience": "someone-else"}, "bad_id_token"),
        ({"expires_in": -3600}, "bad_id_token"),
        ({"keys": attacker_keys()}, "bad_id_token"),
        ({"kid": "unknown-kid"}, "unknown_key"),
    ],
)
def test_bad_id_tokens(kwargs: dict[str, object], reason: str) -> None:
    token = id_token(client_id=CLIENT, nonce=NONCE, email="a@acme.test", **kwargs)  # type: ignore[arg-type]
    assert _reason(token) == reason


def test_wrong_nonce_is_refused() -> None:
    token = id_token(client_id=CLIENT, nonce="other", email="a@acme.test")
    assert _reason(token) == "wrong_nonce"


def test_alg_none_is_refused() -> None:
    claims = jwt.decode(
        id_token(client_id=CLIENT, nonce=NONCE, email="a@acme.test"),
        options={"verify_signature": False},
    )
    head = base64.urlsafe_b64encode(json.dumps({"alg": "none", "kid": "test-key-1"}).encode())
    body = base64.urlsafe_b64encode(json.dumps(claims).encode())
    token = head.rstrip(b"=").decode() + "." + body.rstrip(b"=").decode() + "."
    assert _reason(token) in ("bad_id_token", "unsupported_alg")


def test_hmac_with_public_key_confusion_is_refused() -> None:
    """Classic RS256→HS256 downgrade: sign with the public key as an HMAC secret."""
    claims = jwt.decode(
        id_token(client_id=CLIENT, nonce=NONCE, email="a@acme.test"),
        options={"verify_signature": False},
    )
    public_pem = idp_keys().cert_pem.encode()
    import hmac as _hmac

    head = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "kid": "test-key-1", "typ": "JWT"}).encode()
    ).rstrip(b"=")
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
    sig = base64.urlsafe_b64encode(
        _hmac.new(public_pem, head + b"." + body, hashlib.sha256).digest()
    ).rstrip(b"=")
    assert _reason((head + b"." + body + b"." + sig).decode()) == "unsupported_alg"


def test_missing_email_is_refused() -> None:
    token = id_token(client_id=CLIENT, nonce=NONCE, email="", extra={"email": None})
    assert _reason(token) == "no_email"


# -- PKCE + authorization URL ------------------------------------------------------------------


def test_pkce_pair_is_s256() -> None:
    verifier, challenge = oidc.pkce_pair()
    assert 43 <= len(verifier) <= 128
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    assert challenge == digest.decode()


def test_authorization_url() -> None:
    d = oidc.Discovery.from_document(discovery_document())
    url = oidc.authorization_url(
        d,
        client_id=CLIENT,
        redirect_uri="https://api.builder.test/sso/oidc/acme/callback",
        state="st",
        nonce=NONCE,
        code_challenge="ch",
        login_hint="alice@acme.test",
    )
    parsed = urllib.parse.urlparse(url)
    q = dict(urllib.parse.parse_qsl(parsed.query))
    assert url.startswith(OIDC_ISSUER + "/authorize?")
    assert q == {
        "response_type": "code",
        "client_id": CLIENT,
        "redirect_uri": "https://api.builder.test/sso/oidc/acme/callback",
        "scope": "openid email profile",
        "state": "st",
        "nonce": NONCE,
        "code_challenge": "ch",
        "code_challenge_method": "S256",
        "login_hint": "alice@acme.test",
    }


# -- discovery + token exchange over (fake) HTTP ----------------------------------------------


def _transport(seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json=discovery_document())
        if request.url.path == "/jwks":
            return httpx.Response(200, json=jwks())
        if request.url.path == "/token":
            return httpx.Response(200, json={"id_token": "the-id-token", "access_token": "x"})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def test_discovery_and_code_exchange(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []
    monkeypatch.setattr(oidc, "TRANSPORT", _transport(seen))
    d = await oidc.fetch_discovery(OIDC_DISCOVERY_URL, allow_private=False, require_https=True)
    assert d.token_endpoint == OIDC_ISSUER + "/token"
    keys = await oidc.fetch_jwks(d, allow_private=False, require_https=True)
    assert keys["keys"][0]["kid"] == "test-key-1"
    token = await oidc.exchange_code(
        d,
        code="the-code",
        client_id=CLIENT,
        client_secret="s3cret",
        redirect_uri="https://api.builder.test/cb",
        code_verifier="v" * 43,
        allow_private=False,
        require_https=True,
    )
    assert token == "the-id-token"
    post = seen[-1]
    form = dict(urllib.parse.parse_qsl(post.content.decode()))
    assert form["grant_type"] == "authorization_code"
    assert form["code_verifier"] == "v" * 43
    assert "client_secret" not in form  # client_secret_basic is preferred
    expected = base64.b64encode(f"{CLIENT}:s3cret".encode()).decode()
    assert post.headers["authorization"] == f"Basic {expected}"


async def test_discovery_must_name_https_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = {**discovery_document(), "token_endpoint": "http://login.oidc.example.test/token"}
    monkeypatch.setattr(
        oidc, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(200, json=doc))
    )
    with pytest.raises(oidc.OidcError) as err:
        await oidc.fetch_discovery(OIDC_DISCOVERY_URL, allow_private=False, require_https=True)
    assert err.value.reason == "insecure_url"


async def test_discovery_errors_are_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        oidc, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(500, text="boom"))
    )
    with pytest.raises(oidc.OidcError) as err:
        await oidc.fetch_discovery(OIDC_DISCOVERY_URL, allow_private=False, require_https=True)
    assert err.value.reason == "discovery_failed"


async def test_token_endpoint_error_is_a_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(200, json=discovery_document())

    monkeypatch.setattr(oidc, "TRANSPORT", httpx.MockTransport(handler))
    d = await oidc.fetch_discovery(OIDC_DISCOVERY_URL, allow_private=False, require_https=True)
    with pytest.raises(oidc.OidcError) as err:
        await oidc.exchange_code(
            d,
            code="c",
            client_id=CLIENT,
            client_secret="s",
            redirect_uri="https://x.test/cb",
            code_verifier="v" * 43,
            allow_private=False,
            require_https=True,
        )
    assert err.value.reason == "token_exchange_failed"


# -- outbound URL guard (SSRF) ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://login.example.test/x", "insecure_url"),
        ("https://internal.test/x", "private_address"),
        ("https://meta.test/x", "private_address"),
        ("https://127.0.0.1/x", "private_address"),
        ("https://[::1]/x", "private_address"),
        ("https://user:pw@login.example.test/x", "invalid_url"),
        ("ftp://login.example.test/x", "invalid_url"),
        ("https:///nohost", "invalid_url"),
    ],
)
async def test_outbound_guard_refuses(url: str, reason: str) -> None:
    with pytest.raises(oidc.OidcError) as err:
        await oidc.check_outbound_url(url, allow_private=False, require_https=True)
    assert err.value.reason == reason


async def test_outbound_guard_allows_public_https_and_opt_ins() -> None:
    await oidc.check_outbound_url(
        "https://login.example.test/x", allow_private=False, require_https=True
    )
    # Self-hosted IdP on the internal network, and plain http on a laptop: explicit opt-ins.
    await oidc.check_outbound_url("https://internal.test/x", allow_private=True, require_https=True)
    await oidc.check_outbound_url(
        "http://login.example.test/x", allow_private=False, require_https=False
    )
