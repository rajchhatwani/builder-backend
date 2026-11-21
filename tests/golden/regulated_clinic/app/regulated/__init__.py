"""Regulated mode (generated): protected fields are encrypted at rest (or tokenised) with customer-managed keys.

  settings.py   which table columns are protected, and how (data from the spec)
  keys.py       the keyring (file / command / env), purpose-bound subkeys
  crypto.py     AES-256-GCM, blind index
  fieldtype.py  the SQLAlchemy column types
  tokens.py     the token vault
  orm.py        the before_flush listener (blind indexes, tokens)
  reencrypt.py  `python -m app.regulated.reencrypt`: move every row to the active key

The rule: nothing but the API response to an authorised caller and the encrypted column may hold a protected value.
`mask` replaces the values for anything that copies a row somewhere else, and the protected field names are
registered with app.core.redact so logs and audit records never show them."""

from typing import Any

from app.core import redact
from app.regulated import orm, settings

MASK = "[protected]"
__all__ = ["MASK", "mask", "orm", "protected_columns"]


def protected_columns(table: str) -> frozenset[str]:
    return frozenset(settings.PROTECTED.get(table, {}))


def mask(table: str, payload: dict[str, Any]) -> dict[str, Any]:
    """A copy of `payload` with every protected field of `table` replaced by "[protected]" (None stays None)."""
    protected = protected_columns(table)
    return {k: (MASK if k in protected and v is not None else v) for k, v in payload.items()}


redact.register_secret_keys(settings.REDACT_KEYS)
