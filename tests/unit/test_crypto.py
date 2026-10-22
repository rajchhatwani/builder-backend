"""Unit tests for app.core.crypto (Fernet-based encryption utilities).

All tests set SECRET_KEY in the environment so no real env config is required.
"""

import os

import pytest
from cryptography.fernet import InvalidToken


@pytest.fixture(autouse=True)
def _set_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide a fixed SECRET_KEY for all crypto tests."""
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-unit-tests-only")
    # Force the cached Fernet instance to be rebuilt with this key.
    import app.core.crypto as crypto_module  # noqa: PLC0415

    crypto_module._fernet = None  # reset cache so the monkeypatched key is used


def test_encrypt_returns_string() -> None:
    from app.core.crypto import encrypt

    result = encrypt("hello")
    assert isinstance(result, str)
    assert len(result) > 0


def test_decrypt_round_trips() -> None:
    from app.core.crypto import decrypt, encrypt

    plaintext = "super-secret-password-123"
    assert decrypt(encrypt(plaintext)) == plaintext


def test_none_passthrough_encrypt() -> None:
    from app.core.crypto import encrypt

    assert encrypt(None) is None


def test_none_passthrough_decrypt() -> None:
    from app.core.crypto import decrypt

    assert decrypt(None) is None


def test_encrypted_value_is_not_plaintext() -> None:
    from app.core.crypto import encrypt

    plaintext = "my_twilio_account_sid"
    ciphertext = encrypt(plaintext)
    assert ciphertext is not None
    assert plaintext not in ciphertext


def test_different_plaintexts_produce_different_ciphertexts() -> None:
    """Fernet includes a random IV — same plaintext → different ciphertext each time."""
    from app.core.crypto import encrypt

    c1 = encrypt("same-value")
    c2 = encrypt("same-value")
    assert c1 != c2  # random IV guarantees this


def test_tampered_ciphertext_raises() -> None:
    from app.core.crypto import decrypt, encrypt

    ciphertext = encrypt("secret")
    assert ciphertext is not None
    tampered = ciphertext[:-4] + "XXXX"  # corrupt the MAC
    with pytest.raises(InvalidToken):
        decrypt(tampered)


def test_wrong_key_raises() -> None:
    """Ciphertext from one key cannot be decrypted with another key."""
    import app.core.crypto as crypto_module  # noqa: PLC0415
    from app.core.crypto import encrypt

    ciphertext = encrypt("secret")

    # Switch to a different key
    crypto_module._fernet = None
    os.environ["SECRET_KEY"] = "totally-different-key-xyz-abc-123"
    crypto_module._fernet = None  # force re-derive

    from app.core.crypto import decrypt

    with pytest.raises(InvalidToken):
        decrypt(ciphertext)


def test_missing_secret_key_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.core.crypto as crypto_module  # noqa: PLC0415
    from app.core.crypto import encrypt

    monkeypatch.delenv("SECRET_KEY", raising=False)
    crypto_module._fernet = None  # force re-derive

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        encrypt("any-value")
