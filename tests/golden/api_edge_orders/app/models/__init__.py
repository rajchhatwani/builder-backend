"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.api_edge import models as _api_edge_models
from app.auth import models as _auth_models
from app.models import _associations
from app.models._base import Base
from app.models.customers import Customer
from app.models.orders import Order

__all__ = [
    "Base",
    "Customer",
    "Order",
    "_associations",
    "_auth_models",
    "_api_edge_models",
]
