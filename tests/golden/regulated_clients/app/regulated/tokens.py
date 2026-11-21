"""Tokenisation of regulated mode (generated).

A `tokenise` field stores a deterministic token `tok_<26 chars of base32(HMAC)>` in its own column. The original is
kept ONLY in the vault table `regulated_tokens(token pk, ciphertext, created_at)`, encrypted like any protected
value (AAD `regulated_tokens.value`). `detokenise` is the one way back and nothing calls it on its own.

Design: tokenising needs the database session (the vault row), but a column type has none. So app/regulated/orm.py
registers a `before_flush` listener: for every pending or changed instance of a mapped entity with tokenised fields it
calls `tokenise_sync`, which writes the vault row (INSERT ... ON CONFLICT DO NOTHING, same transaction as the row
itself) and replaces the plain value on the instance with its token. `TokenisedText` refuses any value that is not a
token, so a write that does not go through the session cannot store plaintext.

The token is an HMAC under a purpose-bound subkey of the ring key. While that key is in the ring the same value always
gives the same token (lookups of the vault by candidate tokens, active key first). After the minting key is retired the
same value gets a NEW token; tokens already stored stay valid and detokenise keeps working."""

import base64
import hashlib
import hmac
import re
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.regulated import crypto, keys

VAULT_TABLE = "regulated_tokens"
VAULT_COLUMN = "value"
TOKEN_RE = re.compile(r"tok_[A-Z2-7]{26}")

_vault = sa.table(
    VAULT_TABLE,
    sa.column("token", sa.Text()),
    sa.column("ciphertext", sa.Text()),
    sa.column("created_at", sa.DateTime(timezone=True)),
)


def is_token(value: str) -> bool:
    return TOKEN_RE.fullmatch(value) is not None


def token_for(table: str, column: str, value: str, key_id: str | None = None) -> str:
    key = keys.derive(f"token:{table}.{column}", key_id)
    mac = hmac.new(key, f"{table}.{column}|{value}".encode(), hashlib.sha256).digest()
    return "tok_" + base64.b32encode(mac).decode().rstrip("=")[:26]


def _candidates(table: str, column: str, value: str) -> list[str]:
    ring = keys.get_ring()
    ids = [ring.active_id, *(k for k in ring.keys if k != ring.active_id)]
    return [token_for(table, column, value, kid) for kid in ids]


def tokenise_sync(session: Session, table: str, column: str, value: str) -> str:
    """The token of `value` (created and vaulted when new). Runs in the caller's transaction."""
    candidates = _candidates(table, column, value)
    found = set(session.execute(sa.select(_vault.c.token).where(_vault.c.token.in_(candidates))).scalars())
    for token in candidates:
        if token in found:
            return token
    token = candidates[0]
    session.execute(
        pg_insert(_vault)
        .values(token=token, ciphertext=crypto.encrypt(VAULT_TABLE, VAULT_COLUMN, value), created_at=sa.func.now())
        .on_conflict_do_nothing(index_elements=["token"])
    )
    return token


async def tokenise(session: AsyncSession, table: str, column: str, value: str) -> str:
    """Explicit tokenisation (outside an entity write). The vault row joins the session's transaction."""
    return await session.run_sync(lambda s: tokenise_sync(s, table, column, value))


def detokenise_sync(session: Session, token: str) -> str | None:
    if not is_token(token):
        return None
    stored: Any = session.execute(sa.select(_vault.c.ciphertext).where(_vault.c.token == token)).scalar_one_or_none()
    if stored is None:
        return None
    return crypto.decrypt(VAULT_TABLE, VAULT_COLUMN, stored)


async def detokenise(session: AsyncSession, token: str) -> str | None:
    """The original value of a token, or None when the token is unknown. The only way back from a token:
    call it on purpose, from code that is allowed to see the value."""
    return await session.run_sync(lambda s: detokenise_sync(s, token))
