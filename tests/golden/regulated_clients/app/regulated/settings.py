"""Regulated mode settings (generated). Plain data from the spec; the keys themselves are never here."""

from typing import Any

# The key provider the spec chose; REGULATED_KEY_PROVIDER in the environment overrides it.
KEY_PROVIDER = 'file'

# table -> column -> {"mode": "encrypt" | "tokenise", "searchable": bool}
PROTECTED: dict[str, dict[str, dict[str, Any]]] = {'customers': {'api_token': {'mode': 'tokenise', 'searchable': False},
               'email': {'mode': 'encrypt', 'searchable': True}}}

# Field-name fragments hidden from logs and audit records (the protected fields plus observability.extra_redact_keys).
REDACT_KEYS: tuple[str, ...] = ("api_token", "email")
