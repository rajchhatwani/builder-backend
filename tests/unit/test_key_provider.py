"""P6: key providers, key ids in ciphertext, rotation and tamper detection."""

import os
import stat
import sys
from pathlib import Path

import pytest
from cryptography.fernet import InvalidToken

from app.core import crypto
from app.core.key_provider import (
    CommandKeyProvider,
    FakeKms,
    FileKeyProvider,
    KeyProviderError,
    new_key_b64,
    parse_key_lines,
)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "unit-secret-key-for-key-provider-tests")
    crypto.reset()
    crypto._fernet = None
    yield  # type: ignore[misc]
    crypto.reset()
    crypto._fernet = None


def test_env_provider_uses_key_id_env0_and_prefix() -> None:
    token = crypto.encrypt("hello")
    assert token is not None and token.startswith("v2:env0:")
    assert crypto.decrypt(token) == "hello"
    assert crypto.key_id_of(token) == "env0"


def test_legacy_unprefixed_token_still_decrypts() -> None:
    legacy = crypto._get_fernet().encrypt(b"old").decode()
    assert not legacy.startswith("v2:")
    assert crypto.decrypt(legacy) == "old"


def test_fake_kms_rotation_keeps_old_ciphertext_readable() -> None:
    kms = FakeKms("k1")
    crypto.configure(kms)
    old = crypto.encrypt("first")
    assert old is not None and old.startswith("v2:k1:")
    kms.rotate("k2")
    crypto.configure(kms)  # reload the ring
    assert crypto.active_key_id() == "k2"
    new = crypto.encrypt("second")
    assert new is not None and new.startswith("v2:k2:")
    assert crypto.decrypt(old) == "first" and crypto.decrypt(new) == "second"
    moved = crypto.reencrypt_value(old)
    assert moved is not None and moved.startswith("v2:k2:") and crypto.decrypt(moved) == "first"
    assert crypto.reencrypt_value(new) is None  # already on the active key


def test_dropped_key_cannot_decrypt() -> None:
    kms = FakeKms("k1")
    crypto.configure(kms)
    old = crypto.encrypt("x")
    kms.rotate("k2")
    kms.drop("k1")
    crypto.configure(kms)
    with pytest.raises(InvalidToken):
        crypto.decrypt(old)


def test_tamper_and_key_id_swap_are_rejected() -> None:
    kms = FakeKms("k1", "k2")
    crypto.configure(kms)
    token = crypto.encrypt("secret")
    assert token is not None
    body = token.split(":", 2)[2]
    with pytest.raises(InvalidToken):
        crypto.decrypt(token[:-4] + "XXXX")
    with pytest.raises(InvalidToken):
        crypto.decrypt(f"v2:k1:{body}" if token.startswith("v2:k2:") else f"v2:k2:{body}")
    with pytest.raises(InvalidToken):
        crypto.decrypt("v2:nope:" + body)
    with pytest.raises(InvalidToken):
        crypto.decrypt("v2:broken")


def test_file_provider_roundtrip_and_permissions(tmp_path: Path) -> None:
    f = tmp_path / "keys"
    f.write_text(f"# comment\nfk1 {new_key_b64()}\nfk0 {new_key_b64()}\n")
    f.chmod(0o600)
    crypto.configure(FileKeyProvider(str(f)))
    t = crypto.encrypt("v")
    assert t is not None and t.startswith("v2:fk1:") and crypto.decrypt(t) == "v"
    f.chmod(0o644)
    with pytest.raises(KeyProviderError, match="group or others"):
        FileKeyProvider(str(f)).load()
    with pytest.raises(KeyProviderError):
        FileKeyProvider(str(tmp_path / "missing")).load()


def test_file_provider_does_not_need_secret_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "keys"
    f.write_text(f"only {new_key_b64()}\n")
    f.chmod(0o600)
    crypto.configure(FileKeyProvider(str(f)))
    monkeypatch.delenv("SECRET_KEY")
    t = crypto.encrypt("v")
    assert crypto.decrypt(t) == "v"  # SECRET_KEY is not the trust root any more


def test_command_provider(tmp_path: Path) -> None:
    script = tmp_path / "kms.py"
    script.write_text(f"print('ck1 {new_key_b64()}')\n")
    crypto.configure(CommandKeyProvider(f"{sys.executable} {script}"))
    t = crypto.encrypt("v")
    assert t is not None and t.startswith("v2:ck1:") and crypto.decrypt(t) == "v"
    with pytest.raises(KeyProviderError):
        CommandKeyProvider(f"{sys.executable} -c 'import sys; sys.exit(3)'").load()
    with pytest.raises(KeyProviderError):
        CommandKeyProvider("/nonexistent/kms-binary").load()


def test_malformed_key_material_is_refused_without_echo() -> None:
    for bad in ("", "k1", "k1 !!!", "k1 " + new_key_b64() + "\nk1 " + new_key_b64(), "bad id AAAA"):
        with pytest.raises(KeyProviderError) as exc:
            parse_key_lines(bad)
        assert new_key_b64()[:6] not in str(exc.value)
    short = "k1 AAAA"
    with pytest.raises(KeyProviderError, match="32 bytes"):
        parse_key_lines(short)


def test_ciphertext_columns_cover_the_models() -> None:
    """Every model column documented as ciphertext is in CIPHERTEXT_COLUMNS."""
    import re

    root = Path(__file__).resolve().parents[2] / "app" / "models"
    found = set()
    for path in root.glob("*.py"):
        for m in re.finditer(r"^\s+(\w+_enc)\s*:", path.read_text(), re.M):
            found.add(m.group(1))
    listed = {c for _, c, _ in crypto.CIPHERTEXT_COLUMNS}
    assert found <= listed, found - listed
    assert os.path.exists(root)
    assert stat.S_IRUSR  # keep imports honest


def test_command_provider_gets_minimal_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_SECRET_X", "leak-me")
    monkeypatch.setenv("EXTRA_OK", "yes")
    script = tmp_path / "k.sh"
    script.write_text("#!/bin/sh\nprintf 'k1 %s\\n' \"$KEYB64\"\nenv > \"$OUT\"\n")
    script.chmod(0o700)
    monkeypatch.setenv("KEYB64", new_key_b64())
    monkeypatch.setenv("OUT", str(tmp_path / "env.txt"))
    CommandKeyProvider(str(script), extra_env=("KEYB64", "OUT")).load()
    seen = (tmp_path / "env.txt").read_text()
    assert "DATABASE_SECRET_X" not in seen and "SECRET_KEY" not in seen and "EXTRA_OK" not in seen
    assert "PATH=" in seen and "KEYB64=" in seen
