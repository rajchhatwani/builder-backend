"""Importing this package registers every table on `Base.metadata` (used by Alembic)."""

from app.auth import models as _auth_models
from app.change_history import models as _change_history_models
from app.models import _associations
from app.models._base import Base
from app.models.notes import Note
from app.models.tickets import Ticket
from app.state_machines import models as _state_machine_models

__all__ = [
    "Base",
    "Note",
    "Ticket",
    "_associations",
    "_auth_models",
    "_state_machine_models",
    "_change_history_models",
]
