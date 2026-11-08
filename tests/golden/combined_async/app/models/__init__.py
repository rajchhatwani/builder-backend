"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.api_edge import models as _api_edge_models
from app.auth import models as _auth_models
from app.events import models as _event_models
from app.jobs import models as _job_models
from app.models import _associations
from app.models._base import Base
from app.models.customers import Customer
from app.models.orders import Order
from app.providers import models as _provider_models
from app.state_machines import models as _state_machine_models

__all__ = [
    "Base",
    "Customer",
    "Order",
    "_associations",
    "_auth_models",
    "_state_machine_models",
    "_event_models",
    "_provider_models",
    "_job_models",
    "_api_edge_models",
]
