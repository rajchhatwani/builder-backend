"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.auth import models as _auth_models
from app.models import _associations
from app.models._base import Base
from app.models.tickets import Ticket
from app.state_machines import models as _state_machine_models

__all__ = [
    "Base",
    "Ticket",
    "_associations",
    "_auth_models",
    "_state_machine_models",
]
