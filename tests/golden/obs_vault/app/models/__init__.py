"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.auth import models as _auth_models
from app.models import _associations
from app.models._base import Base
from app.models.secrets import Secret

__all__ = [
    "Base",
    "Secret",
    "_associations",
    "_auth_models",
]
