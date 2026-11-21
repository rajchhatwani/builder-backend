"""Regulated mode (generated): the crypto, the keyring, tokens and masking, without a database."""

import base64
from pathlib import Path

import pytest

from app.regulated import crypto, fieldtype, keys, mask, settings, tokens
from app.regulated.errors import RegulatedError
from tests._regulated_support import key_line, write_keys

_ENCRYPTED = [(t, c) for t, rules in sorted(settings.PROTECTED.items()) for c, r in sorted(rules.items()) if r["mode"] == "encrypt"]
_TABLE, _COLUMN = _ENCRYPTED[0] if _ENCRYPTED else (next(iter(settings.PROTECTED)), "value")
SECRET = "plain-value-ZXQ-1234"


def test_encrypt_decrypt_round_trip_hides_the_plaintext() -> None:
    stored = crypto.encrypt(_TABLE, _COLUMN, SECRET)
    assert stored.startswith("rg1:k2:")
    assert SECRET not in stored
    assert crypto.decrypt(_TABLE, _COLUMN, stored) == SECRET


def test_the_same_value_encrypts_differently_each_time() -> None:
    assert crypto.encrypt(_TABLE, _COLUMN, SECRET) != crypto.encrypt(_TABLE, _COLUMN, SECRET)


def test_a_tampered_ciphertext_is_refused() -> None:
    stored = crypto.encrypt(_TABLE, _COLUMN, SECRET)
    head, body = stored.rsplit(":", 1)
    blob = bytearray(base64.urlsafe_b64decode(body))
    blob[-1] ^= 1
    with pytest.raises(RegulatedError):
        crypto.decrypt(_TABLE, _COLUMN, head + ":" + base64.urlsafe_b64encode(bytes(blob)).decode())


def test_a_ciphertext_moved_to_another_column_does_not_decrypt() -> None:
    stored = crypto.encrypt(_TABLE, _COLUMN, SECRET)
    with pytest.raises(RegulatedError):
        crypto.decrypt(_TABLE, _COLUMN + "_other", stored)
    with pytest.raises(RegulatedError):
        crypto.decrypt(_TABLE + "_other", _COLUMN, stored)


def test_a_value_that_is_not_ciphertext_fails_closed() -> None:
    with pytest.raises(RegulatedError):
        crypto.decrypt(_TABLE, _COLUMN, SECRET)


def test_rotation_keeps_old_rows_readable_and_a_removed_key_fails_closed(regulated_keys: Path) -> None:
    old = crypto.encrypt(_TABLE, _COLUMN, SECRET)  # under k2
    write_keys(regulated_keys, key_line("k3", 3), key_line("k2", 2))
    assert crypto.encrypt(_TABLE, _COLUMN, SECRET).startswith("rg1:k3:")
    assert crypto.decrypt(_TABLE, _COLUMN, old) == SECRET
    write_keys(regulated_keys, key_line("k3", 3))
    with pytest.raises(RegulatedError):
        crypto.decrypt(_TABLE, _COLUMN, old)


def test_a_key_file_open_to_others_is_refused(regulated_keys: Path) -> None:
    regulated_keys.chmod(0o644)
    keys.reset()
    with pytest.raises(RegulatedError, match="chmod 600"):
        keys.get_ring()


def test_error_messages_never_carry_key_material() -> None:
    with pytest.raises(RegulatedError) as exc:
        keys.parse_key_lines("k1 not-base64-at-all!!")
    assert "not-base64" not in str(exc.value)


def test_the_purpose_bound_subkeys_differ() -> None:
    assert keys.derive("a") != keys.derive("b")
    assert keys.derive("a") == keys.derive("a")
    assert keys.derive("a", "k1") != keys.derive("a", "k2")


def test_a_token_is_deterministic_and_does_not_contain_the_value() -> None:
    token = tokens.token_for("t", "c", SECRET)
    assert tokens.is_token(token)
    assert token == tokens.token_for("t", "c", SECRET)
    assert SECRET not in token
    assert token != tokens.token_for("t", "c", SECRET + "x")
    assert token != tokens.token_for("t", "d", SECRET)


def test_a_tokenised_column_refuses_plaintext() -> None:
    column = fieldtype.TokenisedText("t", "c")
    with pytest.raises(RegulatedError):
        column.process_bind_param(SECRET, None)  # type: ignore[arg-type]


def test_mask_replaces_protected_values_only() -> None:
    rules = settings.PROTECTED[_TABLE]
    payload = {name: SECRET for name in rules} | {"id": "1", "empty": None}
    masked = mask(_TABLE, payload)
    assert all(masked[name] == "[protected]" for name in rules)
    assert masked["id"] == "1" and masked["empty"] is None


def test_blind_index_is_stable_normalised_and_hides_the_value() -> None:
    searchable = [(t, c) for t, c in _ENCRYPTED if settings.PROTECTED[t][c]["searchable"]]
    if not searchable:
        pytest.skip("no searchable field")
    table, column = searchable[0]
    assert crypto.blind_index(table, column, " Ann@Example.com ") == crypto.blind_index(table, column, "ann@example.com")
    assert SECRET not in crypto.blind_index(table, column, SECRET)
