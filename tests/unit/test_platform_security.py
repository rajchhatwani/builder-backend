"""Credential primitives: passwords, JWTs, opaque tokens, rate limiting, permission tables."""

import base64
import json

import pytest

from app.core import platform_authz as authz
from app.core import platform_security as sec
from app.core.ratelimit import SlidingWindowLimiter
from app.models.enums import MemberRole, PlatformRole


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "unit-test-secret-key-0123456789abcdef")


def _b64(obj: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()


# -- passwords ---------------------------------------------------------------------------


def test_production_scrypt_cost_is_not_lowered() -> None:
    assert sec.SCRYPT_N == 2**15
    assert sec.hash_password("a-long-enough-password").startswith(f"scrypt${2**15}$8$1$")


def test_password_round_trip_and_wrong_password() -> None:
    stored = sec.hash_password("correct horse battery")
    assert sec.verify_password("correct horse battery", stored)
    assert not sec.verify_password("correct horse batterz", stored)


def test_hashes_are_salted() -> None:
    assert sec.hash_password("same password here") != sec.hash_password("same password here")


@pytest.mark.parametrize(
    "stored",
    ["", "garbage", "scrypt$x$y", "md5$1$2$3$4$5", "scrypt$1$8$1$!!$!!", "scrypt$0$8$1$AA$AA"],
)
def test_malformed_stored_hash_is_a_failed_login_not_a_crash(stored: str) -> None:
    assert sec.verify_password("whatever-password", stored) is False


@pytest.mark.parametrize(
    ("password", "email", "fragment"),
    [
        ("short", "a@b.co", "at least 12"),
        ("x" * 129, "a@b.co", "at most 128"),
        ("aaaaaaaaaaaaaaaa", "a@b.co", "variety"),
        ("johnsmith-password", "johnsmith@example.com", "too easy"),
        ("password1234", "a@b.co", "too easy"),
    ],
)
def test_password_policy_rejects(password: str, email: str, fragment: str) -> None:
    assert any(fragment in problem for problem in sec.password_problems(password, email))


def test_password_policy_accepts_a_passphrase() -> None:
    assert sec.password_problems("purple-giraffe-eats-lunch", "a@b.co") == []


# -- JWT ---------------------------------------------------------------------------------


def _token(**overrides: object) -> str:
    claims = sec.access_claims(
        user_id="u1", audience=sec.AUDIENCE_APP, token_version=0, ttl_seconds=900, now=1_000_000
    )
    claims.update(overrides)
    return sec.encode_jwt(claims)


def test_jwt_round_trip() -> None:
    claims = sec.decode_jwt(_token(), audience=sec.AUDIENCE_APP, now=1_000_100)
    assert claims["sub"] == "u1"
    assert claims["tv"] == 0


def test_jwt_expires_after_ttl_plus_leeway() -> None:
    token = _token()
    sec.decode_jwt(token, audience=sec.AUDIENCE_APP, now=1_000_000 + 900 + 30)
    with pytest.raises(sec.TokenError, match="expired"):
        sec.decode_jwt(token, audience=sec.AUDIENCE_APP, now=1_000_000 + 900 + 31)


def test_jwt_audiences_are_not_interchangeable() -> None:
    with pytest.raises(sec.TokenError, match="audience"):
        sec.decode_jwt(_token(), audience=sec.AUDIENCE_ADMIN, now=1_000_100)


def test_jwt_wrong_issuer_rejected() -> None:
    with pytest.raises(sec.TokenError, match="issuer"):
        sec.decode_jwt(_token(iss="someone-else"), audience=sec.AUDIENCE_APP, now=1_000_100)


def test_jwt_issued_in_the_future_rejected() -> None:
    with pytest.raises(sec.TokenError, match="future"):
        sec.decode_jwt(_token(), audience=sec.AUDIENCE_APP, now=1_000_000 - 3600)


def test_jwt_tampered_payload_rejected() -> None:
    head, _, sig = _token().split(".")
    forged = _b64(
        {**json.loads(base64.urlsafe_b64decode(_token().split(".")[1] + "==")), "sub": "admin"}
    )
    with pytest.raises(sec.TokenError, match="signature"):
        sec.decode_jwt(f"{head}.{forged}.{sig}", audience=sec.AUDIENCE_APP, now=1_000_100)


def test_jwt_alg_none_rejected() -> None:
    body = _token().split(".")[1]
    for alg in ("none", "None", "NONE", "HS512", "RS256"):
        forged = f"{_b64({'alg': alg, 'typ': 'JWT'})}.{body}."
        with pytest.raises(sec.TokenError, match="algorithm"):
            sec.decode_jwt(forged, audience=sec.AUDIENCE_APP, now=1_000_100)


@pytest.mark.parametrize("junk", ["", "a.b", "a.b.c.d", "....", "not a token", "ey.ey.ey"])
def test_jwt_garbage_rejected(junk: str) -> None:
    with pytest.raises(sec.TokenError):
        sec.decode_jwt(junk, audience=sec.AUDIENCE_APP)


def test_jwt_signed_with_another_secret_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    token = _token()
    monkeypatch.setenv("SECRET_KEY", "a-completely-different-secret-value-xyz")
    with pytest.raises(sec.TokenError, match="signature"):
        sec.decode_jwt(token, audience=sec.AUDIENCE_APP, now=1_000_100)


def test_missing_secret_key_is_a_loud_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SECRET_KEY")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        sec.encode_jwt({"sub": "x"})


@pytest.mark.parametrize(
    ("secret", "env", "ok"),
    [
        ("", "local", False),
        ("short", "local", True),
        ("short", "production", False),
        ("a" * 40, "production", False),  # long but no variety
        ("Zk3-9fQ_pLw2xRv7TnB5yHcJ8dMa4sUe6gXo1iKq", "production", True),
        ("local-development-only-secret-key-change-me", "production", False),  # compose default
        ("local-development-only-secret-key-change-me", "local", True),
    ],
)
def test_secret_strength(secret: str, env: str, ok: bool) -> None:
    assert (sec.check_secret_strength(secret, env) is None) is ok


# -- opaque tokens -----------------------------------------------------------------------


def test_api_token_shape_and_lookup() -> None:
    token, public_id, digest = sec.new_api_token()
    assert token.startswith("bb_pat_")
    assert sec.parse_api_token(token) == public_id
    assert digest == sec.hash_token(token)
    assert token not in digest and len(digest) == 64


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "bb_pat_",
        "bb_pat_short_x",
        "xx_pat_abcdefghij_" + "a" * 43,
        "bb_pat_abcdefghij_" + "!" * 43,
    ],
)
def test_parse_api_token_rejects_malformed(bad: str) -> None:
    assert sec.parse_api_token(bad) is None


def test_tokens_are_unique() -> None:
    assert len({sec.new_refresh_token()[0] for _ in range(50)}) == 50
    assert len({sec.new_api_token()[0] for _ in range(50)}) == 50


# -- rate limiter ------------------------------------------------------------------------


def test_limiter_blocks_then_recovers() -> None:
    now = [0.0]
    limiter = SlidingWindowLimiter(3, 60, clock=lambda: now[0])
    assert [limiter.allow("ip") for _ in range(4)] == [True, True, True, False]
    assert limiter.allow("other")  # keys are independent
    assert limiter.retry_after("ip") >= 1
    now[0] = 61
    assert limiter.allow("ip")


def test_limiter_memory_is_bounded() -> None:
    now = [0.0]
    limiter = SlidingWindowLimiter(1, 10, clock=lambda: now[0], max_keys=100)
    for i in range(100):
        limiter.allow(f"k{i}")
    now[0] = 100
    limiter.allow("fresh")
    assert len(limiter._hits) <= 101


# -- permission tables (decision tables: any change here is a deliberate security change) -----

PROJECT = "/projects/{project_id}"


@pytest.mark.parametrize(
    ("method", "template", "needed"),
    [
        ("GET", PROJECT, MemberRole.viewer),
        ("HEAD", PROJECT, MemberRole.viewer),
        ("PATCH", PROJECT, MemberRole.editor),
        ("DELETE", PROJECT, MemberRole.owner),
        ("GET", f"{PROJECT}/entities", MemberRole.viewer),
        ("POST", f"{PROJECT}/entities", MemberRole.editor),
        ("DELETE", "/entities/{entity_id}", MemberRole.editor),
        ("GET", f"{PROJECT}/members", MemberRole.viewer),
        ("POST", f"{PROJECT}/members", MemberRole.owner),
        ("PATCH", f"{PROJECT}/members/{{user_id}}", MemberRole.owner),
        ("DELETE", f"{PROJECT}/members/{{user_id}}", MemberRole.owner),
        ("PUT", f"{PROJECT}/auth/secrets", MemberRole.owner),
        ("GET", f"{PROJECT}/auth/secrets/status", MemberRole.viewer),
        ("GET", f"{PROJECT}/generate/download", MemberRole.viewer),
        ("POST", f"{PROJECT}/payments/enable", MemberRole.editor),
    ],
)
def test_required_member_role(method: str, template: str, needed: MemberRole) -> None:
    assert authz.required_member_role(method, template) is needed


@pytest.mark.parametrize(
    ("method", "template", "scope"),
    [
        ("GET", f"{PROJECT}/entities", "read"),
        ("POST", f"{PROJECT}/entities", "write"),
        ("GET", f"{PROJECT}/generate/download", "generate"),
        ("POST", f"{PROJECT}/generate/preview", "generate"),
        ("GET", "/generations/{generation_id}", "generate"),
    ],
)
def test_required_scope(method: str, template: str, scope: str) -> None:
    assert authz.required_scope(method, template) == scope


def test_scope_inclusion() -> None:
    assert authz.scopes_allow(frozenset({"write"}), "read")
    assert not authz.scopes_allow(frozenset({"read"}), "write")
    assert not authz.scopes_allow(frozenset({"write"}), "generate")  # a zip leaves the platform
    assert not authz.scopes_allow(frozenset(), "read")


def test_admin_permissions_decision_table() -> None:
    assert not any(
        authz.admin_can(PlatformRole.customer, p)
        for p in ("users:read", "audit:read", "stats:read")
    )
    assert authz.admin_can(PlatformRole.platform_support, "users:read")
    assert not authz.admin_can(PlatformRole.platform_support, "users:write")
    assert authz.admin_can(PlatformRole.platform_admin, "users:write")
    assert not authz.admin_can(
        PlatformRole.platform_admin, "projects:write"
    )  # admins never edit specs
    assert not authz.admin_can(PlatformRole.platform_admin, "unknown:permission")
