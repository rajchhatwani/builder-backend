"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.auth import models as _auth_models
from app.change_history import models as _change_history_models
from app.models import _associations
from app.models._base import Base
from app.models.employees import Employee
from app.realtime import models as _realtime_models
from app.state_machines import models as _state_machine_models

__all__ = [
    "Base",
    "Employee",
    "_associations",
    "_auth_models",
    "_state_machine_models",
    "_change_history_models",
    "_realtime_models",
]
