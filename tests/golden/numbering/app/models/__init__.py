"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.auth import models as _auth_models
from app.models import _associations
from app.models._base import Base
from app.models.orders import Order
from app.runtime_config import models as _runtime_config_models
from app.seed import models as _seed_models
from app.state_machines import models as _state_machine_models

__all__ = [
    "Base",
    "Order",
    "_associations",
    "_auth_models",
    "_runtime_config_models",
    "_state_machine_models",
    "_seed_models",
]
