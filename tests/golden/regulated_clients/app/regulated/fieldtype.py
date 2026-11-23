"""SQLAlchemy column types of regulated mode (generated).

EncryptedText   the column holds ciphertext (`rg1:...`): encrypted on the way in, decrypted on the way out.
TokenisedText   the column holds a token (`tok_...`). The write path (app/regulated/orm.py) swaps the value for its
                token and stores the original in the vault before the row is flushed; this type refuses anything that is
                not a token, so a write that bypassed the listener (a Core insert) fails closed instead of storing
                plaintext. Reading gives the token back; only `tokens.detokenise` returns the original."""

from typing import Any

from sqlalchemy import Text
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from app.regulated import crypto, tokens
from app.regulated.errors import RegulatedError


class EncryptedText(TypeDecorator[str]):
    impl = Text
    cache_ok = True

    def __init__(self, table: str, column: str) -> None:
        super().__init__()
        self.table = table
        self.column = column

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        return None if value is None else crypto.encrypt(self.table, self.column, value)

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        return None if value is None else crypto.decrypt(self.table, self.column, value)

    def __repr__(self) -> str:
        return f"EncryptedText({self.table!r}, {self.column!r})"


class TokenisedText(TypeDecorator[str]):
    impl = Text
    cache_ok = True

    def __init__(self, table: str, column: str) -> None:
        super().__init__()
        self.table = table
        self.column = column

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not tokens.is_token(value):
            raise RegulatedError(f"{self.table}.{self.column} accepts tokens only: write it through the session")
        return value

    def __repr__(self) -> str:
        return f"TokenisedText({self.table!r}, {self.column!r})"
