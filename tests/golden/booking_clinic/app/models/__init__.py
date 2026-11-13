"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.auth import models as _auth_models
from app.booking import models as _booking_models
from app.models import _associations
from app.models._base import Base
from app.models.services import Service

__all__ = [
    "Base",
    "Service",
    "_associations",
    "_auth_models",
    "_booking_models",
]
