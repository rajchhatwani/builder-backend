"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.models import _associations
from app.models._base import Base
from app.models.notes import Note

__all__ = [
    "Base",
    "Note",
    "_associations",
]
