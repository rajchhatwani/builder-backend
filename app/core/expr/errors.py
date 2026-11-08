"""Errors of the expression engine. Anything a user can cause is an ExprError with a position."""


class ExprError(Exception):
    def __init__(self, message: str, pos: int = 0) -> None:
        super().__init__(message)
        self.message = message
        self.pos = pos

    def __str__(self) -> str:
        return f"{self.message} (at character {self.pos})"

# One class only: runtime.py is copied into generated projects and defines it there.
from app.core.expr.runtime import ExprOverflow as ExprOverflow  # noqa: E402
