"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.auth import models as _auth_models
from app.models import _associations
from app.models._base import Base
from app.models.customers import Customer
from app.models.deals import Deal

__all__ = [
    "Base",
    "Customer",
    "Deal",
    "_associations",
    "_auth_models",
]
