"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.auth import models as _auth_models
from app.events import models as _event_models
from app.models import _associations
from app.models._base import Base
from app.models.customers import Customer
from app.models.orders import Order
from app.state_machines import models as _state_machine_models

__all__ = [
    "Base",
    "Customer",
    "Order",
    "_associations",
    "_auth_models",
    "_state_machine_models",
    "_event_models",
]
