"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.auth import models as _auth_models
from app.models import _associations
from app.models._base import Base
from app.models.orders import Order
from app.payments import models as _payments_models
from app.storage import models as _storage_models

__all__ = [
    "Base",
    "Order",
    "_associations",
    "_auth_models",
    "_payments_models",
    "_storage_models",
]
