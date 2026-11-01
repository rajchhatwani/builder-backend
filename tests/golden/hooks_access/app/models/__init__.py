"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.auth import models as _auth_models
from app.models import _associations
from app.models._base import Base
from app.models.ledgers import Ledger
from app.models.notes import Note

__all__ = [
    "Base",
    "Ledger",
    "Note",
    "_associations",
    "_auth_models",
]
