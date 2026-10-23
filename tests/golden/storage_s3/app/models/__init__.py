"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.auth import models as _auth_models
from app.models import _associations
from app.models._base import Base
from app.models.photos import Photo
from app.storage import models as _storage_models

__all__ = [
    "Base",
    "Photo",
    "_associations",
    "_auth_models",
    "_storage_models",
]
