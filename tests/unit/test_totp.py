"""Built-in TOTP (RFC 6238 / RFC 4226), PLATFORM_SAAS_PLAN §4.4 Phase 1."""

import base64
import urllib.parse

import pytest

from app.core import totp

# RFC 6238 Appendix B, SHA-1 column: the shared secret is the ASCII string below, 8 digits.
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()
RFC_VECTORS = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]


@pytest.mark.parametrize(("at", "expected"), RFC_VECTORS)
def test_rfc6238_vectors(at: int, expected: str) -> None:
    assert totp.code_at(RFC_SECRET, at, digits=8) == expected


def test_new_secret_is_160_bit_base32() -> None:
    secret = totp.new_secret()
    assert len(base64.b32decode(secret)) == 20
    assert secret != totp.new_secret()


def test_verify_accepts_current_and_adjacent_steps_and_returns_the_step() -> None:
    secret = totp.new_secret()
    now = 1_700_000_000
    step = now // 30
    assert totp.verify(secret, totp.code_at(secret, now), now=now) == step
    assert totp.verify(secret, totp.code_at(secret, now - 30), now=now) == step - 1
    assert totp.verify(secret, totp.code_at(secret, now + 30), now=now) == step + 1
    assert totp.verify(secret, totp.code_at(secret, now - 90), now=now) is None


def test_verify_refuses_replay_of_a_used_step() -> None:
    secret = totp.new_secret()
    now = 1_700_000_000
    code = totp.code_at(secret, now)
    step = now // 30
    assert totp.verify(secret, code, now=now, last_step=step) is None
    assert totp.verify(secret, code, now=now, last_step=step - 1) == step


@pytest.mark.parametrize("bad", ["", "12345", "1234567", "abcdef", "12 34 5x", None])
def test_verify_refuses_malformed_codes(bad: str | None) -> None:
    assert totp.verify(totp.new_secret(), bad, now=1_700_000_000) is None  # type: ignore[arg-type]


def test_verify_tolerates_spaces() -> None:
    secret = totp.new_secret()
    code = totp.code_at(secret, 1_700_000_000)
    assert totp.verify(secret, f"{code[:3]} {code[3:]}", now=1_700_000_000) is not None


def test_otpauth_uri() -> None:
    uri = totp.otpauth_uri("JBSWY3DPEHPK3PXP", account="a+b@example.com", issuer="Builder")
    parsed = urllib.parse.urlparse(uri)
    assert parsed.scheme == "otpauth" and parsed.netloc == "totp"
    assert urllib.parse.unquote(parsed.path) == "/Builder:a+b@example.com"
    q = urllib.parse.parse_qs(parsed.query)
    assert q == {
        "secret": ["JBSWY3DPEHPK3PXP"],
        "issuer": ["Builder"],
        "algorithm": ["SHA1"],
        "digits": ["6"],
        "period": ["30"],
    }


def test_recovery_codes_are_unique_readable_and_normalised() -> None:
    codes = totp.new_recovery_codes()
    assert len(codes) == 10 and len(set(codes)) == 10
    for c in codes:
        assert len(c) == 11 and c[5] == "-"
    assert totp.normalize_recovery_code(" " + codes[0].upper().replace("-", "") + " ") == (
        codes[0].replace("-", "").lower()
    )
